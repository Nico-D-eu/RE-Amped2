using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Threading;

namespace Amped2Installer
{
    /// <summary>
    /// The zip build.ps1 embeds: amped2\ and xboxrecomp\ (the sources the
    /// game is built from), tools\xdvdfs.exe and manifest.txt. No game data.
    /// </summary>
    static class Payload
    {
        static string _scratch;

        static Stream Open()
        {
            var s = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip");
            if (s != null)
                return s;
            // Development runs (dotnet run) without an embedded payload.
            var exeDir = AppDomain.CurrentDomain.BaseDirectory;
            foreach (var candidate in new[] { Path.Combine(exeDir, "payload.zip"),
                                              Path.Combine(exeDir, @"..\..\obj\payload.zip") })
                if (File.Exists(candidate))
                    return File.OpenRead(candidate);
            return null;
        }

        public static bool Available
        {
            get { using (var s = Open()) return s != null; }
        }

        /// <summary>A private temp folder for this run, removed on exit.</summary>
        public static string Scratch
        {
            get
            {
                if (_scratch == null)
                {
                    _scratch = Path.Combine(Path.GetTempPath(), "RE-Amped2-Setup-" + Guid.NewGuid().ToString("N").Substring(0, 8));
                    Directory.CreateDirectory(_scratch);
                }
                return _scratch;
            }
        }

        public static void CleanScratch()
        {
            try { if (_scratch != null) Directory.Delete(_scratch, true); } catch (Exception) { }
        }

        static string _xdvdfs;

        /// <summary>The disc extractor, unpacked from the payload on first use.</summary>
        public static string Xdvdfs
        {
            get
            {
                if (_xdvdfs == null)
                {
                    var dest = Path.Combine(Scratch, "xdvdfs.exe");
                    ExtractFile("tools/xdvdfs.exe", dest);
                    _xdvdfs = dest;
                }
                return _xdvdfs;
            }
        }

        /// <summary>
        /// The licence texts in the payload, and the names they get in a
        /// "licenses" folder: RE-Amped2's, the toolkit's (with its LGPL part)
        /// and those of the tools the installer carries.
        /// </summary>
        static readonly (string Entry, string Name)[] LicenseFiles =
        {
            ("amped2/LICENSE", "RE-Amped2-LICENSE.txt"),
            ("amped2/NOTICE.md", "RE-Amped2-NOTICE.txt"),
            ("xboxrecomp/LICENSE", "xboxrecomp-LICENSE.txt"),
            ("xboxrecomp/NOTICE", "xboxrecomp-NOTICE.txt"),
            ("xboxrecomp/LICENSES/LGPL-2.1.txt", "LGPL-2.1.txt"),
            ("amped2/licenses/xdvdfs-LICENSE.txt", "xdvdfs-LICENSE.txt"),
            ("amped2/licenses/unluac-LICENSE.txt", "unluac-LICENSE.txt"),
        };

        /// <summary>Writes the licence texts into <paramref name="destDir"/>; returns how many it found.</summary>
        public static int ExtractLicenses(string destDir)
        {
            int n = 0;
            foreach (var (entry, name) in LicenseFiles)
            {
                try
                {
                    ExtractFile(entry, System.IO.Path.Combine(destDir, name));
                    n++;
                }
                catch (FileNotFoundException) { }
            }
            return n;
        }

        public static void ExtractFile(string entryName, string destPath)
        {
            using (var s = Open())
            {
                if (s == null)
                    throw new InvalidOperationException("This installer is incomplete (no payload). Download it again.");
                using (var zip = new ZipArchive(s, ZipArchiveMode.Read))
                {
                    var entry = zip.GetEntry(entryName)
                                ?? throw new FileNotFoundException("Missing from the installer: " + entryName);
                    Directory.CreateDirectory(Path.GetDirectoryName(destPath));
                    entry.ExtractToFile(destPath, true);
                }
            }
        }

        /// <summary>Unpacks every entry under destDir; reports (done, total).</summary>
        public static void ExtractAll(string destDir, Action<int, int> progress, CancellationToken ct)
        {
            using (var s = Open())
            {
                if (s == null)
                    throw new InvalidOperationException("This installer is incomplete (no payload). Download it again.");
                using (var zip = new ZipArchive(s, ZipArchiveMode.Read))
                {
                    var root = Path.GetFullPath(destDir).TrimEnd('\\') + "\\";
                    int done = 0, total = zip.Entries.Count;
                    foreach (var entry in zip.Entries)
                    {
                        ct.ThrowIfCancellationRequested();
                        var path = Path.GetFullPath(Path.Combine(root, entry.FullName.Replace('/', '\\')));
                        if (!path.StartsWith(root, StringComparison.OrdinalIgnoreCase))
                            throw new InvalidDataException("Bad path in the installer payload: " + entry.FullName);
                        if (entry.FullName.EndsWith("/"))
                            Directory.CreateDirectory(path);
                        else
                        {
                            Directory.CreateDirectory(Path.GetDirectoryName(path));
                            entry.ExtractToFile(path, true);
                        }
                        progress?.Invoke(++done, total);
                    }
                }
            }
        }

        static Dictionary<string, string> _manifest;

        /// <summary>key=value lines build.ps1 writes: versions of the sources inside.</summary>
        public static Dictionary<string, string> Manifest
        {
            get
            {
                if (_manifest != null)
                    return _manifest;
                _manifest = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                try
                {
                    using (var s = Open())
                    using (var zip = new ZipArchive(s, ZipArchiveMode.Read))
                    using (var r = new StreamReader(zip.GetEntry("manifest.txt").Open()))
                    {
                        string line;
                        while ((line = r.ReadLine()) != null)
                        {
                            int eq = line.IndexOf('=');
                            if (eq > 0)
                                _manifest[line.Substring(0, eq).Trim()] = line.Substring(eq + 1).Trim();
                        }
                    }
                }
                catch (Exception) { }
                return _manifest;
            }
        }
    }
}
