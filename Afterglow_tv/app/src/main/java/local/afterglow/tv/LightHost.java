package local.afterglow.tv;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.LinkAddress;
import android.net.LinkProperties;
import android.net.Network;
import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Semaphore;

final class LightHost {
    static final int PORT = 8765;
    private static final String ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz";
    private static final String SECURITY = "Cache-Control: no-store\r\n"
            + "X-Content-Type-Options: nosniff\r\nReferrer-Policy: no-referrer\r\n"
            + "Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; "
            + "connect-src 'self'; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'\r\n";
    static final String HEARTBEAT = "event: heartbeat\ndata: {}\n\n";
    static final LightHost INSTANCE = new LightHost();

    private final Map<String, byte[]> assets = new HashMap<>();
    private final Object changed = new Object();
    private volatile String status = "idle";
    private volatile int receivers;
    private volatile Listener listener;
    private String event = eventJson("idle", Palette.BLACK);
    private long revision;

    private LightHost() {}

    String status() { return status; }
    int receivers() { return receivers; }
    boolean capturing() { return "waiting".equals(status) || "live".equals(status); }
    String address() { Listener value = listener; return value == null ? "" : value.url; }
    String code() { Listener value = listener; return value == null ? "" : value.code; }

    synchronized boolean refresh(Context context) {
        ConnectivityManager manager = (ConnectivityManager) context.getSystemService(Context.CONNECTIVITY_SERVICE);
        Network active = manager.getActiveNetwork();
        LinkAddress link = findLan(active == null ? null : manager.getLinkProperties(active));
        if (link == null) {
            for (Network network : manager.getAllNetworks()) {
                // Prefer wired Ethernet or Wi-Fi when the default network is a VPN.
                android.net.NetworkCapabilities caps = manager.getNetworkCapabilities(network);
                if (caps == null || !(caps.hasTransport(android.net.NetworkCapabilities.TRANSPORT_ETHERNET)
                        || caps.hasTransport(android.net.NetworkCapabilities.TRANSPORT_WIFI))) continue;
                link = findLan(manager.getLinkProperties(network));
                if (link != null) break;
            }
        }
        if (listener != null && listener.link.equals(link)) return true;
        close();
        if (link == null) return false;
        try {
            if (assets.isEmpty()) {
                Map<String, byte[]> loaded = new HashMap<>();
                for (String file : new String[] {"light.html", "style.css", "light.js", "gradient.js"}) {
                    loaded.put(file, readAsset(context, file));
                }
                for (String placement : new String[] {"behind-tv", "below-tv", "tv-stand"}) {
                    String file = "guides/" + placement + ".mp4";
                    loaded.put(file, readAsset(context, file));
                }
                assets.putAll(loaded);
            }
            Listener created = new Listener(link);
            listener = created;
            worker("Afterglow LAN", created::accept);
            return true;
        } catch (IOException error) {
            return false;
        }
    }

    private static byte[] readAsset(Context context, String file) throws IOException {
        try (InputStream stream = context.getAssets().open(file)) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            int size;
            while ((size = stream.read(buffer)) != -1) bytes.write(buffer, 0, size);
            return bytes.toByteArray();
        }
    }

    private static LinkAddress findLan(LinkProperties properties) {
        if (properties != null) {
            for (LinkAddress link : properties.getLinkAddresses()) {
                InetAddress address = link.getAddress();
                if (address instanceof Inet4Address && address.isSiteLocalAddress()
                        && link.getPrefixLength() > 0) return link;
            }
        }
        return null;
    }

    synchronized void close() {
        Listener old = listener;
        listener = null;
        if (old != null) old.close();
        synchronized (changed) {
            receivers = 0;
            changed.notifyAll();
        }
    }

    void publish(String state, int[][][] palettes) {
        String next = eventJson(state, palettes);
        synchronized (changed) {
            status = state;
            if (!event.equals(next)) {
                event = next;
                revision++;
                changed.notifyAll();
            }
        }
    }

    static boolean sameSubnet(byte[] host, byte[] peer, int prefix) {
        if (peer.length != 4) return false;
        for (int i = 0; i < host.length && prefix > 0; i++, prefix -= 8) {
            int mask = 0xff << (8 - Math.min(8, prefix));
            if (((host[i] ^ peer[i]) & 0xff & mask) != 0) return false;
        }
        return true;
    }

    static boolean paired(String target, String code) {
        String path = "/api/light?key=";
        if (!target.startsWith(path) || target.length() != path.length() + code.length()) return false;
        for (int i = path.length(); i < target.length(); i++) {
            if (ALPHABET.indexOf(target.charAt(i)) < 0) return false;
        }
        return MessageDigest.isEqual(target.substring(path.length()).getBytes(StandardCharsets.US_ASCII),
                code.getBytes(StandardCharsets.US_ASCII));
    }

    static String eventJson(String state, int[][][] palettes) {
        StringBuilder json = new StringBuilder(680).append("data: {\"status\":\"").append(state)
                .append("\",\"placement\":\"center\",\"orientation\":\"auto\",\"mirror\":true,")
                .append("\"boost\":true,\"level\":100,\"colors\":");
        appendPalette(json, palettes[0]);
        json.append(",\"palettes\":{");
        for (int i = 0; i < Palette.PLACEMENTS.length; i++) {
            if (i != 0) json.append(',');
            json.append('"').append(Palette.PLACEMENTS[i]).append("\":");
            appendPalette(json, palettes[i]);
        }
        return json.append("}}\n\n").toString();
    }

    private static void appendPalette(StringBuilder json, int[][] colors) {
        json.append('[');
        for (int i = 0; i < colors.length; i++) {
            if (i != 0) json.append(',');
            json.append('[').append(colors[i][0]).append(',').append(colors[i][1])
                    .append(',').append(colors[i][2]).append(']');
        }
        json.append(']');
    }

    private static void worker(String name, Runnable work) {
        Thread thread = new Thread(work, name);
        thread.setDaemon(true);
        thread.start();
    }

    static String requestTarget(InputStream input) throws IOException {
        // Each connection accepts one request. Limit the entire header, including the request line.
        byte[] bytes = new byte[8192];
        int count = 0;
        while (count < bytes.length) {
            int value = input.read();
            if (value == -1) return null;
            bytes[count++] = (byte) value;
            if (count >= 4 && bytes[count - 4] == '\r' && bytes[count - 3] == '\n'
                    && bytes[count - 2] == '\r' && bytes[count - 1] == '\n') {
                int end = 0;
                while (bytes[end] != '\r' && bytes[end] != '\n') end++;
                String[] request = new String(bytes, 0, end, StandardCharsets.US_ASCII).split(" ", -1);
                return request.length == 3 && "GET".equals(request[0])
                        && ("HTTP/1.1".equals(request[2]) || "HTTP/1.0".equals(request[2]))
                        ? request[1] : null;
            }
        }
        return null;
    }

    private final class Listener {
        final LinkAddress link;
        final ServerSocket server;
        final String url;
        final String code;
        final Semaphore requests = new Semaphore(24), streams = new Semaphore(8);
        final Set<Socket> sockets = ConcurrentHashMap.newKeySet();

        Listener(LinkAddress link) throws IOException {
            this.link = link;
            StringBuilder key = new StringBuilder(8);
            SecureRandom random = new SecureRandom();
            for (int i = 0; i < 8; i++) key.append(ALPHABET.charAt(random.nextInt(ALPHABET.length())));
            code = key.toString();
            server = new ServerSocket();
            try {
                server.setReuseAddress(true);
                server.bind(new InetSocketAddress(link.getAddress(), PORT));
            } catch (IOException portInUse) {
                try {
                    server.bind(new InetSocketAddress(link.getAddress(), 0));
                } catch (IOException error) {
                    server.close();
                    throw error;
                }
            }
            url = "http://" + link.getAddress().getHostAddress() + ":" + server.getLocalPort() + "/light";
        }

        void accept() {
            try {
                while (listener == this) {
                    Socket socket = server.accept();
                    if (listener != this || !socket.getInetAddress().isSiteLocalAddress()
                            || !sameSubnet(link.getAddress().getAddress(), socket.getInetAddress().getAddress(),
                                    link.getPrefixLength()) || !requests.tryAcquire()) {
                        socket.close();
                        continue;
                    }
                    sockets.add(socket);
                    if (listener != this) {
                        sockets.remove(socket);
                        requests.release();
                        socket.close();
                        break;
                    }
                    worker("Afterglow phone", () -> handle(socket));
                }
            } catch (IOException ignored) {
                synchronized (LightHost.this) {
                    if (listener == this) LightHost.this.close();
                }
            }
        }

        void close() {
            try { server.close(); } catch (IOException ignored) {}
            for (Socket socket : sockets) {
                try { socket.close(); } catch (IOException ignored) {}
            }
        }

        void handle(Socket socket) {
            try (Socket connection = socket) {
                connection.setSoTimeout(3500);
                connection.setTcpNoDelay(true);
                String target = requestTarget(new BufferedInputStream(connection.getInputStream()));
                OutputStream output = connection.getOutputStream();
                if (target == null) {
                    respond(output, "400 Bad Request", "text/plain", new byte[0]);
                } else if (target.startsWith("/api/light?")) {
                    if (paired(target, code)) stream(output);
                    else respond(output, "403 Forbidden", "text/plain", new byte[0]);
                } else {
                    String file = "/".equals(target) || "/light".equals(target)
                            ? "light.html" : target.startsWith("/") ? target.substring(1) : "";
                    byte[] body = assets.get(file);
                    if (body == null) respond(output, "404 Not Found", "text/plain", new byte[0]);
                    else respond(output, "200 OK", file.endsWith(".html") ? "text/html" :
                            file.endsWith(".css") ? "text/css" :
                            file.endsWith(".mp4") ? "video/mp4" : "text/javascript", body);
                }
            } catch (IOException ignored) {
                // The phone can disconnect at any point in the request or stream.
            } finally {
                sockets.remove(socket);
                requests.release();
            }
        }

        void stream(OutputStream output) throws IOException {
            if (!streams.tryAcquire()) {
                respond(output, "503 Service Unavailable", "text/plain", new byte[0]);
                return;
            }
            synchronized (changed) {
                if (listener != this) {
                    streams.release();
                    return;
                }
                receivers++;
            }
            try {
                headers(output, "200 OK", "text/event-stream", -1);
                long last = -1;
                while (listener == this) {
                    String next;
                    synchronized (changed) {
                        if (last == revision && listener == this) changed.wait(1500);
                        if (listener != this) break;
                        next = last == revision ? HEARTBEAT : event;
                        last = revision;
                    }
                    output.write(next.getBytes(StandardCharsets.UTF_8));
                    output.flush();
                }
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
            } finally {
                synchronized (changed) {
                    if (listener == this) receivers--;
                }
                streams.release();
            }
        }
    }

    private static void respond(OutputStream output, String status, String type, byte[] body)
            throws IOException {
        headers(output, status, type, body.length);
        output.write(body);
        output.flush();
    }

    private static void headers(OutputStream output, String status, String type, int size) throws IOException {
        output.write(("HTTP/1.1 " + status + "\r\nConnection: close\r\n" + SECURITY
                + "Content-Type: " + type + "; charset=utf-8\r\n"
                + (size >= 0 ? "Content-Length: " + size + "\r\n" : "") + "\r\n")
                .getBytes(StandardCharsets.US_ASCII));
    }
}
