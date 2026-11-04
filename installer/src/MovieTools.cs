using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Threading;

namespace Amped2Installer
{
    /// <summary>
    /// The HD movies: FFmpeg and Real-ESRGAN, fetched from their publishers'
    /// GitHub releases at fixed versions (SHA-256 checked) into
    /// &lt;install&gt;\tools\bin, and tools\mods\movie_pack.py, which converts
    /// the player's movies into mods\movie_pack after the install. The
    /// installer ships neither tool; they are downloaded on the player's PC,
    /// only with their consent (ConsentDialog).
    /// </summary>
    static class MovieTools
    {
        public sealed class Tool
        {
            public string Name, Publisher, Purpose, Note, LicenseUrl;
            public string Url, Sha256;
            public string Folder;                       // under tools\bin
            /// <summary>Where a zip entry goes, relative to Folder; null leaves it out.</summary>
            public Func<string, string> Keep;
        }

        public const string FFmpegTool = "FFmpeg";
        public const string EsrganTool = "Real-ESRGAN";

        /// <summary>
        /// BtbN's month-end autobuilds stay published (the daily ones and
        /// "latest" are replaced), so a fixed one keeps its URL and hash. To
        /// move to a newer version, change the URL and hash together.
        /// </summary>
        public static readonly Tool[] Tools =
        {
            new Tool
            {
                Name = FFmpegTool,
                Publisher = "The FFmpeg project, built by BtbN",
                Purpose = "reads the game's movies and writes the HD copies",
                Note = "77 MB download, LGPL build",
                LicenseUrl = "https://ffmpeg.org/legal.html",
                Url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-10-31-12-59/" +
                      "ffmpeg-n9.0.2-39-g7adfbe40dc-win64-lgpl-shared-9.0.zip",
                Sha256 = "e907b01fa4783913151237e37df2a10fa97d99a1598a021bf59d4ae62ffed4c0",
                Folder = "ffmpeg",
                // <top>/bin/* without the player, and <top>/LICENSE.txt.
                Keep = e =>
                {
                    var rel = e.Substring(e.IndexOf('/') + 1);
                    if (rel == "LICENSE.txt") return rel;
                    return rel.StartsWith("bin/") && rel.Length > 4 && rel != "bin/ffplay.exe" ? rel : null;
                },
            },
            new Tool
            {
                Name = EsrganTool,
                Publisher = "Xintao Wang (xinntao)",
                Purpose = "upscales the movies' pictures on your graphics card",
                Note = "45 MB download, BSD-3-Clause",
                LicenseUrl = "https://github.com/xinntao/Real-ESRGAN/blob/master/LICENSE",
                Url = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip",
                Sha256 = "abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d",
                Folder = "realesrgan",
                // The program, its OpenMP runtime and the fast video model.
                Keep = e => e == "realesrgan-ncnn-vulkan.exe" || e == "vcomp140.dll" || e == "README_windows.md" ||
                            e.StartsWith("models/realesr-animevideov3-") ? e : null,
            },
        };

        /// <summary>
        /// Downloads and unpacks each tool unless the same version is already
        /// there (a stamp file holds its hash). Throws on any failure.
        /// </summary>
        public static void Fetch(string installDir, string scratch, Action<string> detail, Action<string> log,
                                 Action<double> fraction, CancellationToken ct)
        {
            ServicePointManager.SecurityProtocol |= SecurityProtocolType.Tls12;
            Directory.CreateDirectory(scratch);
            for (int i = 0; i < Tools.Length; i++)
            {
                var t = Tools[i];
                var dir = Path.Combine(installDir, @"tools\bin", t.Folder);
                var stamp = Path.Combine(dir, ".sha256");
                if (File.Exists(stamp) && File.ReadAllText(stamp).Trim() == t.Sha256)
                {
                    log($"{t.Name}: already there");
                    continue;
                }
                var zip = Path.Combine(scratch, t.Folder + ".zip");
                Download(t, zip, s => detail(s), f => fraction((i + 0.9 * f) / Tools.Length), log, ct);

                detail($"Unpacking {t.Name}");
                if (Directory.Exists(dir))
                    Directory.Delete(dir, true);
                int n = 0;
                using (var a = ZipFile.OpenRead(zip))
                    foreach (var e in a.Entries)
                    {
                        var rel = e.Name.Length > 0 ? t.Keep(e.FullName) : null;
                        if (rel == null) continue;
                        var to = Path.Combine(dir, rel.Replace('/', '\\'));
                        Directory.CreateDirectory(Path.GetDirectoryName(to));
                        e.ExtractToFile(to, true);
                        n++;
                    }
                File.WriteAllText(stamp, t.Sha256);
                File.Delete(zip);
                log($"{t.Name}: {n} files in {dir}");
            }
            fraction(1);
        }

        static void Download(Tool t, string file, Action<string> detail, Action<double> fraction, Action<string> log,
                             CancellationToken ct)
        {
            log($"{t.Name}: {t.Url}");
            var req = (HttpWebRequest)WebRequest.Create(t.Url);
            req.UserAgent = "RE-Amped2-Setup";
            using (var resp = (HttpWebResponse)req.GetResponse())
            using (var src = resp.GetResponseStream())
            using (var dst = File.Create(file))
            using (var sha = SHA256.Create())
            {
                long total = resp.ContentLength, done = 0;
                var buf = new byte[1 << 16];
                int got;
                while ((got = src.Read(buf, 0, buf.Length)) > 0)
                {
                    ct.ThrowIfCancellationRequested();
                    dst.Write(buf, 0, got);
                    sha.TransformBlock(buf, 0, got, null, 0);
                    done += got;
                    if (total > 0)
                    {
                        fraction((double)done / total);
                        detail($"Downloading {t.Name} ({done >> 20} of {total >> 20} MB)");
                    }
                }
                sha.TransformFinalBlock(buf, 0, 0);
                var hash = string.Concat(sha.Hash.Select(b => b.ToString("x2")));
                if (hash != t.Sha256)
                    throw new IOException($"{t.Name} download has SHA-256 {hash}, expected {t.Sha256}");
            }
        }

        public static string Script(string installDir) => Path.Combine(installDir, @"tools\mods\movie_pack.py");
        public static string Launcher(string installDir) => Path.Combine(installDir, "Convert HD movies.cmd");

        /// <summary>
        /// Puts movie_pack.py beside the game and writes the launcher, which
        /// runs it with this Python (or py -3 if that Python is gone). The
        /// recipe skips finished movies, so the launcher also resumes.
        /// </summary>
        public static void WriteLauncher(string installDir, string recipe, string python)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(Script(installDir)));
            File.Copy(recipe, Script(installDir), true);
            var text = new StringBuilder()
                .AppendLine("@echo off")
                .AppendLine("chcp 65001 >nul")
                .AppendLine("rem RE-Amped2: converts the game's movies to HD copies in mods\\movie_pack.")
                .AppendLine("rem Finished movies are skipped, so running this again carries on where it stopped.")
                .AppendLine("title RE-Amped2: converting the movies to HD")
                .AppendLine("cd /d \"%~dp0\"")
                .AppendLine("echo Converting the movies to HD. This takes a few hours; each movie is used in the")
                .AppendLine("echo game as soon as it is done. You can play meanwhile, or close this window and")
                .AppendLine("echo run \"Convert HD movies.cmd\" later to carry on.")
                .AppendLine("echo.")
                .AppendLine($"set \"PY={python}\"")
                .AppendLine("if exist \"%PY%\" (\"%PY%\" -I tools\\mods\\movie_pack.py %*) else (py -3 -I tools\\mods\\movie_pack.py %*)")
                .AppendLine("echo.")
                .AppendLine("pause");
            // UTF-8 (chcp 65001 above) so a Python path with non-ASCII letters survives.
            File.WriteAllText(Launcher(installDir), text.ToString(), new UTF8Encoding(false));
        }

        /// <summary>Starts the launcher minimised, below normal priority so the PC (and the game) stay responsive.</summary>
        public static void Start(string installDir)
        {
            var p = Process.Start(new ProcessStartInfo(Launcher(installDir))
            {
                UseShellExecute = true,
                WorkingDirectory = installDir,
                WindowStyle = ProcessWindowStyle.Minimized,
            });
            try { p.PriorityClass = ProcessPriorityClass.BelowNormal; } catch (Exception) { }   // its children inherit it
        }
    }
}
