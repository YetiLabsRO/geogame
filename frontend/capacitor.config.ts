import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'ro.yetilabs.geogame',
  appName: 'Tower Rush',
  webDir: 'dist/player/browser',
  server: {
    androidScheme: 'https',
  },
  plugins: {
    SplashScreen: {
      launchAutoHide: true,
      backgroundColor: '#fcf9f2',
    },
    PushNotifications: {
      presentationOptions: ['badge', 'sound', 'alert'],
    },
  },
  android: {
    allowMixedContent: false,
    // @capacitor-community/background-geolocation requires the legacy bridge,
    // otherwise background location updates stop after ~5 minutes.
    // See node_modules/@capacitor-community/background-geolocation/README.md#android
    useLegacyBridge: true,
  },
};

export default config;
