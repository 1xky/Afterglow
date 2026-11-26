package local.afterglow.tv;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.res.ColorStateList;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Point;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.media.projection.MediaProjectionConfig;
import android.media.projection.MediaProjectionManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class TvActivity extends Activity {
    private static final int CONSENT = 31;
    private static final int TEXT = 0xfff5edff, MUTED = 0xffc3b5d1, ACCENT = 0xffdcc4ff;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService network = Executors.newSingleThreadExecutor();
    private final LightHost host = LightHost.INSTANCE;
    private TextView status, hint, address, code, receivers;
    private Button sync, test, reconnect;
    private QrView qr;
    private String displayedAddress = "", displayedCode = "", message = "";
    private boolean requesting;
    private final Runnable refresh = new Runnable() {
        @Override public void run() {
            render();
            ui.postDelayed(this, 350);
        }
    };

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        requesting = saved != null && saved.getBoolean("requesting");
        // Prevent the dashboard, including its pairing code, from appearing in captures.
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE | WindowManager.LayoutParams.FLAG_FULLSCREEN);
        setContentView(dashboard());
        sync.requestFocus();
    }

    @Override public void onSaveInstanceState(Bundle out) {
        out.putBoolean("requesting", requesting);
        super.onSaveInstanceState(out);
    }

    @Override protected void onStart() {
        super.onStart();
        refreshAddress();
        ui.post(refresh);
    }

    @Override protected void onStop() {
        ui.removeCallbacks(refresh);
        super.onStop();
    }

    @Override protected void onDestroy() {
        network.shutdown();
        super.onDestroy();
    }

    private void refreshAddress() {
        network.execute(() -> {
            host.refresh(getApplicationContext());
            runOnUiThread(this::render);
        });
    }

    private View dashboard() {
        ScrollView page = new ScrollView(this);
        page.setFillViewport(true);
        page.setBackground(new GradientDrawable(GradientDrawable.Orientation.TL_BR,
                new int[] {0xff2b1b3d, 0xff15111d, 0xff121017}));
        LinearLayout body = column();
        body.setPadding(dp(38), dp(24), dp(38), dp(26));
        page.addView(body);
        TextView title = text("Afterglow TV", 37, TEXT, true);
        body.addView(title);
        body.addView(text("Turn your phone into a light that follows the TV.", 17, MUTED, false));

        LinearLayout cards = new LinearLayout(this);
        cards.setOrientation(LinearLayout.HORIZONTAL);
        cards.setBaselineAligned(false);
        LinearLayout.LayoutParams row = new LinearLayout.LayoutParams(-1, -2);
        row.topMargin = dp(20);
        body.addView(cards, row);

        LinearLayout left = card();
        LinearLayout.LayoutParams leftSize = new LinearLayout.LayoutParams(0, -1, 1.14f);
        leftSize.rightMargin = dp(14);
        cards.addView(left, leftSize);
        left.addView(text("Screen sync", 23, TEXT, true));
        status = text("", 18, ACCENT, true);
        left.addView(status, spaced(7));
        hint = text("", 15, MUTED, false);
        hint.setMinLines(3);
        left.addView(hint, spaced(6));
        sync = button("Start sync", true);
        sync.setOnClickListener(view -> toggleCapture());
        left.addView(sync, spaced(10));
        test = button("Test light", false);
        test.setOnClickListener(view -> {
            if (host.capturing() || requesting) return;
            message = "";
            if ("demo".equals(host.status())) host.publish("idle", Palette.BLACK);
            else host.publish("demo", Palette.demo(55));
            render();
        });
        left.addView(test, spaced(8));

        LinearLayout right = card();
        cards.addView(right, new LinearLayout.LayoutParams(0, -1, 1));
        right.addView(text("Pair your phone", 23, TEXT, true));
        receivers = text("", 15, ACCENT, true);
        right.addView(receivers, spaced(5));
        right.addView(text("Scan on the same network. On your phone, open Placement for setup videos.",
                15, MUTED, false), spaced(5));
        qr = new QrView();
        LinearLayout.LayoutParams qrSize = new LinearLayout.LayoutParams(dp(148), dp(148));
        qrSize.gravity = Gravity.CENTER_HORIZONTAL;
        qrSize.topMargin = dp(10);
        right.addView(qr, qrSize);
        address = text("", 15, MUTED, false);
        address.setGravity(Gravity.CENTER);
        right.addView(address, spaced(7));
        code = text("", 23, TEXT, true);
        code.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        code.setGravity(Gravity.CENTER);
        right.addView(code, spaced(3));
        reconnect = button("Refresh connection", false);
        reconnect.setOnClickListener(view -> refreshAddress());
        right.addView(reconnect, spaced(8));
        return page;
    }

    private void toggleCapture() {
        if (requesting) return;
        message = "";
        if (host.capturing()) {
            startService(new Intent(this, CaptureService.class).setAction(CaptureService.STOP));
            return;
        }
        MediaProjectionManager manager = getSystemService(MediaProjectionManager.class);
        try {
            Intent prompt = Build.VERSION.SDK_INT >= 34
                    ? manager.createScreenCaptureIntent(MediaProjectionConfig.createConfigForDefaultDisplay())
                    : manager.createScreenCaptureIntent();
            requesting = true;
            render();
            startActivityForResult(prompt, CONSENT);
        } catch (ActivityNotFoundException | SecurityException error) {
            requesting = false;
            message = "This TV did not open Android's screen capture permission prompt. Test light still works.";
            render();
        }
    }

    @SuppressWarnings("deprecation")
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request != CONSENT) return;
        requesting = false;
        if (result != RESULT_OK || data == null) {
            message = "Screen sharing was cancelled. Select Start sync to try again.";
        } else {
            Point screen = new Point();
            getWindowManager().getDefaultDisplay().getRealSize(screen);
            Intent start = new Intent(this, CaptureService.class).setAction(CaptureService.START)
                    .putExtra("consent", data).putExtra("result", result)
                    .putExtra("width", screen.x).putExtra("height", screen.y)
                    .putExtra("density", getResources().getDisplayMetrics().densityDpi);
            try {
                host.publish("waiting", Palette.BLACK);
                startForegroundService(start);
            } catch (RuntimeException error) {
                host.publish("unavailable", Palette.BLACK);
            }
        }
        render();
    }

    private void render() {
        String state = host.status();
        boolean syncing = host.capturing();
        status.setText("live".equals(state) ? "Syncing" : "waiting".equals(state) ? "Waiting for screen"
                : "demo".equals(state) ? "Test light" : "unavailable".equals(state) ? "Capture unavailable" : "Ready");
        hint.setText(!message.isEmpty() ? message : syncing
                ? "Press Home on the remote and open your video app. Return here to stop sync."
                : "Try Test light after pairing. Then select Start sync and approve screen sharing.");
        sync.setText(syncing ? "Stop sync" : "Start sync");
        sync.setEnabled(!requesting && (syncing || !host.address().isEmpty()));
        test.setText("demo".equals(state) ? "End test" : "Test light");
        test.setEnabled(!requesting && !syncing && !host.address().isEmpty());
        int count = host.receivers();
        receivers.setText(count == 0 ? "No phones connected" :
                count == 1 ? "1 phone connected" : count + " phones connected");
        String url = host.address(), key = host.code();
        if (!url.equals(displayedAddress) || !key.equals(displayedCode)) {
            displayedAddress = url;
            displayedCode = key;
            qr.setLink(url.isEmpty() || key.isEmpty() ? "" : url + "#" + key);
            address.setText(url.isEmpty() ? "Connect the TV to Wi-Fi or Ethernet." : url);
            code.setText(key);
        }
        qr.setVisibility(url.isEmpty() ? View.GONE : View.VISIBLE);
        code.setVisibility(key.isEmpty() ? View.GONE : View.VISIBLE);
        if (url.isEmpty()) address.setText("Connect the TV to Wi-Fi or Ethernet, then refresh.");
        if (getCurrentFocus() == null) {
            if (sync.isEnabled()) sync.requestFocus();
            else reconnect.requestFocus();
        }
    }

    private int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private LinearLayout column() {
        LinearLayout view = new LinearLayout(this);
        view.setOrientation(LinearLayout.VERTICAL);
        return view;
    }

    private LinearLayout card() {
        LinearLayout view = column();
        view.setPadding(dp(17), dp(15), dp(17), dp(15));
        view.setBackground(panel(0xff211a2c, 0xff453951, 1));
        return view;
    }

    private GradientDrawable panel(int fill, int border, int width) {
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(fill);
        shape.setStroke(dp(width), border);
        shape.setCornerRadius(dp(13));
        return shape;
    }

    private LinearLayout.LayoutParams spaced(int margin) {
        LinearLayout.LayoutParams size = new LinearLayout.LayoutParams(-1, -2);
        size.topMargin = dp(margin);
        return size;
    }

    private TextView text(String value, int size, int color, boolean strong) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        if (strong) view.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return view;
    }

    private Button button(String label, boolean primary) {
        Button view = new Button(this);
        view.setText(label);
        view.setAllCaps(false);
        view.setTextSize(16);
        view.setMinHeight(dp(46));
        view.setPadding(dp(12), dp(6), dp(12), dp(6));
        int[] disabled = {-android.R.attr.state_enabled}, focused = {android.R.attr.state_focused};
        StateListDrawable backgrounds = new StateListDrawable();
        backgrounds.addState(disabled, panel(0xff282230, 0xff3e3549, 1));
        backgrounds.addState(focused, panel(ACCENT, 0xffffffff, 3));
        backgrounds.addState(new int[0], panel(primary ? 0xff51366e : 0xff332845, 0xff665478, 1));
        view.setBackground(backgrounds);
        view.setTextColor(new ColorStateList(new int[][] {disabled, focused, new int[0]},
                new int[] {0xffa699af, 0xff23152f, TEXT}));
        view.setFocusable(true);
        return view;
    }

    private final class QrView extends View {
        private final Paint paint = new Paint();
        private boolean[][] modules;
        QrView() {
            super(TvActivity.this);
            setContentDescription("QR code to pair a phone");
        }
        void setLink(String link) {
            modules = link.isEmpty() ? null : PairingQr.encode(link);
            invalidate();
        }
        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            if (modules == null) return;
            int unit = Math.min(getWidth(), getHeight()) / (modules.length + 8);
            int size = unit * (modules.length + 8);
            int left = (getWidth() - size) / 2, top = (getHeight() - size) / 2;
            paint.setColor(Color.WHITE);
            canvas.drawRect(left, top, left + size, top + size, paint);
            paint.setColor(Color.BLACK);
            for (int y = 0; y < modules.length; y++) {
                for (int x = 0; x < modules.length; x++) {
                    if (modules[y][x]) {
                        int px = left + (x + 4) * unit, py = top + (y + 4) * unit;
                        canvas.drawRect(px, py, px + unit, py + unit, paint);
                    }
                }
            }
        }
    }
}
