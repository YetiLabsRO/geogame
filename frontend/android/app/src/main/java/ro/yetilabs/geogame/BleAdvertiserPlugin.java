package ro.yetilabs.geogame;

import android.Manifest;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothManager;
import android.bluetooth.le.AdvertiseCallback;
import android.bluetooth.le.AdvertiseData;
import android.bluetooth.le.AdvertiseSettings;
import android.bluetooth.le.BluetoothLeAdvertiser;
import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.ParcelUuid;

import androidx.core.content.ContextCompat;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.nio.charset.StandardCharsets;
import java.util.UUID;

/**
 * Advertises a small token (the player's ephemeral proximity id) as BLE service data
 * under a fixed game service UUID, for the Dementors proximity mode.
 *
 * There is no maintained Capacitor plugin that supports BLE advertising (only scanning,
 * e.g. @capacitor-community/bluetooth-le), so this local plugin wraps the platform
 * BluetoothLeAdvertiser directly. Permission requests are handled on the JS side via the
 * bluetooth-le plugin; this plugin only checks and reports missing permissions.
 */
@CapacitorPlugin(name = "BleAdvertiser")
public class BleAdvertiserPlugin extends Plugin {

    // Tokens are expected to be <= 16 bytes (UTF-8) to fit comfortably inside a BLE
    // advertisement packet alongside the service UUID and flags.
    private static final int MAX_TOKEN_BYTES = 16;

    private BluetoothLeAdvertiser advertiser;
    private AdvertiseCallback advertiseCallback;

    @PluginMethod
    public void isSupported(PluginCall call) {
        BluetoothAdapter adapter = getAdapter();
        boolean supported =
            adapter != null
                && adapter.isEnabled()
                && (isMultipleAdvertisementSupported(adapter) || adapter.getBluetoothLeAdvertiser() != null);

        JSObject result = new JSObject();
        result.put("supported", supported);
        call.resolve(result);
    }

    @PluginMethod
    public void start(PluginCall call) {
        String serviceUuid = call.getString("serviceUuid");
        String token = call.getString("token");

        if (serviceUuid == null || serviceUuid.isEmpty()) {
            call.reject("serviceUuid is required");
            return;
        }
        if (token == null || token.isEmpty()) {
            call.reject("token is required");
            return;
        }

        if (!hasAdvertisePermission()) {
            call.reject(
                "Missing BLUETOOTH_ADVERTISE permission. Request Bluetooth permissions " +
                "(e.g. through @capacitor-community/bluetooth-le) before calling start()."
            );
            return;
        }

        BluetoothAdapter adapter = getAdapter();
        if (adapter == null || !adapter.isEnabled()) {
            call.reject("Bluetooth is not available or not enabled on this device");
            return;
        }

        BluetoothLeAdvertiser leAdvertiser = adapter.getBluetoothLeAdvertiser();
        if (leAdvertiser == null) {
            call.reject("BLE advertising is not supported on this device");
            return;
        }

        byte[] tokenBytes = token.getBytes(StandardCharsets.UTF_8);
        if (tokenBytes.length > MAX_TOKEN_BYTES) {
            call.reject("token must be at most " + MAX_TOKEN_BYTES + " bytes when UTF-8 encoded");
            return;
        }

        ParcelUuid parcelUuid;
        try {
            parcelUuid = new ParcelUuid(UUID.fromString(serviceUuid));
        } catch (IllegalArgumentException e) {
            call.reject("serviceUuid must be a valid UUID string");
            return;
        }

        // Only one advertise session at a time: replace whatever was running before.
        stopInternal();

        AdvertiseSettings settings = new AdvertiseSettings.Builder()
            .setAdvertiseMode(AdvertiseSettings.ADVERTISE_MODE_LOW_LATENCY)
            .setConnectable(false)
            .setTimeout(0)
            .build();

        AdvertiseData data = new AdvertiseData.Builder()
            .setIncludeDeviceName(false)
            .addServiceUuid(parcelUuid)
            .addServiceData(parcelUuid, tokenBytes)
            .build();

        AdvertiseCallback callback = new AdvertiseCallback() {
            @Override
            public void onStartSuccess(AdvertiseSettings settingsInEffect) {
                call.resolve();
            }

            @Override
            public void onStartFailure(int errorCode) {
                advertiser = null;
                advertiseCallback = null;
                call.reject("Failed to start BLE advertising: " + describeError(errorCode));
            }
        };

        advertiser = leAdvertiser;
        advertiseCallback = callback;

        try {
            leAdvertiser.startAdvertising(settings, data, callback);
        } catch (SecurityException e) {
            advertiser = null;
            advertiseCallback = null;
            call.reject("Missing Bluetooth permission: " + e.getMessage());
        }
    }

    @PluginMethod
    public void stop(PluginCall call) {
        stopInternal();
        call.resolve();
    }

    private void stopInternal() {
        if (advertiser != null && advertiseCallback != null) {
            try {
                advertiser.stopAdvertising(advertiseCallback);
            } catch (SecurityException ignored) {
                // BLUETOOTH_ADVERTISE was revoked between start() and stop(); nothing left to clean up.
            }
        }
        advertiser = null;
        advertiseCallback = null;
    }

    private BluetoothAdapter getAdapter() {
        BluetoothManager manager = (BluetoothManager) getContext().getSystemService(Context.BLUETOOTH_SERVICE);
        return manager != null ? manager.getAdapter() : null;
    }

    @SuppressWarnings("deprecation")
    private boolean isMultipleAdvertisementSupported(BluetoothAdapter adapter) {
        // Deprecated since API 26 in favor of checking getBluetoothLeAdvertiser() != null,
        // but still a useful capability probe on the API levels where it is available.
        return adapter.isMultipleAdvertisementSupported();
    }

    private boolean hasAdvertisePermission() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) {
            // BLUETOOTH_ADVERTISE is a new permission as of API 31; below that, the
            // normal (install-time) BLUETOOTH_ADMIN permission covers advertising.
            return true;
        }
        return ContextCompat.checkSelfPermission(getContext(), Manifest.permission.BLUETOOTH_ADVERTISE)
            == PackageManager.PERMISSION_GRANTED;
    }

    private static String describeError(int errorCode) {
        switch (errorCode) {
            case AdvertiseCallback.ADVERTISE_FAILED_ALREADY_STARTED:
                return "already started";
            case AdvertiseCallback.ADVERTISE_FAILED_DATA_TOO_LARGE:
                return "advertise data too large";
            case AdvertiseCallback.ADVERTISE_FAILED_FEATURE_UNSUPPORTED:
                return "feature unsupported";
            case AdvertiseCallback.ADVERTISE_FAILED_INTERNAL_ERROR:
                return "internal error";
            case AdvertiseCallback.ADVERTISE_FAILED_TOO_MANY_ADVERTISERS:
                return "too many advertisers";
            default:
                return "unknown error " + errorCode;
        }
    }
}
