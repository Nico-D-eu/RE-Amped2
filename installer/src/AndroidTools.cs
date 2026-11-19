namespace Amped2Installer
{
    /// <summary>
    /// What the Android app's build downloads (tools\android\build_android.ps1
    /// pins the versions and hashes), listed for the player's consent.
    /// </summary>
    static class AndroidTools
    {
        public const string Name = "Android tools";

        public sealed class Part
        {
            public string Name, Publisher, Purpose, Note, LicenseUrl;
        }

        public static readonly Part[] Parts =
        {
            new Part
            {
                Name = "Microsoft Build of OpenJDK 17",
                Publisher = "Microsoft",
                Purpose = "runs the Android build tools and compiles the app's Java part",
                Note = "186 MB download, GPLv2 with the Classpath Exception",
                LicenseUrl = "https://learn.microsoft.com/java/openjdk/faq",
            },
            new Part
            {
                Name = "Android SDK and NDK",
                Publisher = "Google",
                Purpose = "compiles the game for Android and packs the app",
                Note = "about 2.5 GB download, Android SDK licence",
                LicenseUrl = "https://developer.android.com/studio/terms",
            },
            new Part
            {
                Name = "SDL 2.30.10",
                Publisher = "The SDL project",
                Purpose = "the app's window, sound and gamepads on Android",
                Note = "8 MB source download, zlib licence",
                LicenseUrl = "https://www.libsdl.org/license.php",
            },
        };
    }
}
