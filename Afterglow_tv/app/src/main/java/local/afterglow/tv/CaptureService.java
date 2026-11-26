package local.afterglow.tv;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.graphics.PixelFormat;
import android.hardware.display.DisplayManager;
import android.hardware.display.VirtualDisplay;
import android.media.Image;
import android.media.ImageReader;
import android.media.projection.MediaProjection;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;
import java.util.Arrays;

public final class CaptureService extends Service {
    static final String START = "local.afterglow.tv.START", STOP = "local.afterglow.tv.STOP";
    private static final String CHANNEL = "afterglow-capture";
    private static final int NOTIFICATION = 81, SAMPLE_EDGE = 192;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final byte[] rgb = new byte[Palette.FRAME_BYTES];
    private final byte[] last = new byte[Palette.FRAME_BYTES];
    private HandlerThread samplingThread;
    private Handler sampling;
    private MediaProjection projection;
    private VirtualDisplay display;
    private ImageReader reader;
    private int density;
    private boolean haveFrame;
    private long sampledAt;

    private final Runnable refreshNetwork = new Runnable() {
        @Override public void run() {
            LightHost.INSTANCE.refresh(getApplicationContext());
            sampling.postDelayed(this, 2000);
        }
    };

    private final MediaProjection.Callback projectionCallback = new MediaProjection.Callback() {
        @Override public void onStop() { finishCapture("idle"); }

        @Override public void onCapturedContentResize(int width, int height) {
            resize(width, height);
        }
    };

    @Override public IBinder onBind(Intent intent) { return null; }

    @Override public void onCreate() {
        super.onCreate();
        samplingThread = new HandlerThread("Afterglow sampling");
        samplingThread.start();
        sampling = new Handler(samplingThread.getLooper());
    }

    @SuppressWarnings("deprecation")
    @Override public int onStartCommand(Intent request, int flags, int startId) {
        if (request == null || STOP.equals(request.getAction())) {
            finishCapture("idle");
            return START_NOT_STICKY;
        }
        if (!START.equals(request.getAction()) || projection != null) return START_NOT_STICKY;
        try {
            NotificationManager notifications = getSystemService(NotificationManager.class);
            notifications.createNotificationChannel(new NotificationChannel(CHANNEL,
                    "Screen sync", NotificationManager.IMPORTANCE_LOW));
            Notification notification = notification();
            if (Build.VERSION.SDK_INT >= 29) {
                startForeground(NOTIFICATION, notification,
                        ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION);
            } else {
                startForeground(NOTIFICATION, notification);
            }

            Intent consent = request.getParcelableExtra("consent");
            MediaProjectionManager manager = getSystemService(MediaProjectionManager.class);
            projection = manager.getMediaProjection(request.getIntExtra("result", 0), consent);
            if (projection == null) throw new IllegalStateException("No screen capture permission.");
            projection.registerCallback(projectionCallback, main);
            density = Math.max(1, request.getIntExtra("density", 160));
            int width = request.getIntExtra("width", 1920);
            int height = request.getIntExtra("height", 1080);
            int[] size = captureSize(width, height);
            reader = openReader(size);
            display = projection.createVirtualDisplay("Afterglow screen colors", size[0], size[1], density,
                    DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, reader.getSurface(), null, sampling);
            if (display == null) throw new IllegalStateException("This TV refused screen capture.");
            LightHost.INSTANCE.publish("waiting", Palette.BLACK);
            sampling.post(refreshNetwork);
        } catch (RuntimeException error) {
            android.util.Log.w("AfterglowTV", "Could not start screen capture", error);
            finishCapture("unavailable");
        }
        return START_NOT_STICKY;
    }

    private Notification notification() {
        int immutable = PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT;
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, TvActivity.class), immutable);
        PendingIntent stop = PendingIntent.getService(this, 1,
                new Intent(this, CaptureService.class).setAction(STOP), immutable);
        return new Notification.Builder(this, CHANNEL)
                .setSmallIcon(android.R.drawable.ic_menu_view)
                .setContentTitle("Afterglow screen sync")
                .setContentText("Sending screen colors to paired phones")
                .setContentIntent(open)
                .addAction(new Notification.Action.Builder(null, "Stop sync", stop).build())
                .setOngoing(true)
                .build();
    }

    private static int[] captureSize(int width, int height) {
        double scale = SAMPLE_EDGE / (double) Math.max(width, height);
        return new int[] {Math.max(1, (int) Math.round(width * scale)),
                Math.max(1, (int) Math.round(height * scale))};
    }

    private ImageReader openReader(int[] size) {
        ImageReader next = ImageReader.newInstance(size[0], size[1], PixelFormat.RGBA_8888, 2);
        next.setOnImageAvailableListener(this::frame, sampling);
        return next;
    }

    private synchronized void resize(int width, int height) {
        if (display == null || width <= 0 || height <= 0) return;
        int[] size = captureSize(width, height);
        if (reader.getWidth() == size[0] && reader.getHeight() == size[1]) return;
        ImageReader previous = reader;
        try {
            reader = openReader(size);
            display.resize(size[0], size[1], density);
            display.setSurface(reader.getSurface());
            haveFrame = false;
        } catch (RuntimeException error) {
            finishCapture("unavailable");
        } finally {
            if (reader != previous) previous.close();
        }
    }

    private synchronized void frame(ImageReader source) {
        if (source != reader || display == null) return;
        try (Image image = source.acquireLatestImage()) {
            long now = SystemClock.elapsedRealtime();
            if (image == null || now - sampledAt < 83) return;
            sampledAt = now;
            Image.Plane plane = image.getPlanes()[0];
            Palette.sample(plane.getBuffer(), image.getWidth(), image.getHeight(),
                    plane.getRowStride(), plane.getPixelStride(), rgb);
            if (!haveFrame || !Arrays.equals(rgb, last)) {
                LightHost.INSTANCE.publish("live", Palette.extract(rgb, 55));
                System.arraycopy(rgb, 0, last, 0, rgb.length);
                haveFrame = true;
            }
        } catch (RuntimeException error) {
            android.util.Log.w("AfterglowTV", "Could not read the capture surface", error);
            main.post(() -> finishCapture("unavailable"));
        }
    }

    private void finishCapture(String status) {
        releaseCapture();
        LightHost.INSTANCE.publish(status, Palette.BLACK);
        stopForeground(STOP_FOREGROUND_REMOVE);
        stopSelf();
    }

    private synchronized void releaseCapture() {
        sampling.removeCallbacks(refreshNetwork);
        if (display != null) { display.release(); display = null; }
        if (reader != null) { reader.close(); reader = null; }
        if (projection != null) {
            projection.unregisterCallback(projectionCallback);
            projection.stop();
            projection = null;
        }
        haveFrame = false;
    }

    @Override public void onDestroy() {
        releaseCapture();
        samplingThread.quitSafely();
        if (LightHost.INSTANCE.capturing()) LightHost.INSTANCE.publish("idle", Palette.BLACK);
        super.onDestroy();
    }
}
