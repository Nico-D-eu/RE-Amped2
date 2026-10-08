using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;

namespace Amped2Installer
{
    sealed class InstallOptions
    {
        public DiscInfo Disc;
        public string InstallDir;
        public bool DesktopShortcut;
        public bool MenuMod;
    }

    sealed class InstallResult
    {
        public bool Success, Cancelled, WasUpdate;
        public string FailedStage, Error, Advice;
        public TimeSpan Duration;
        public string InstallDir, ExePath, LogPath;
        public bool ShortcutCreated, MenuModInstalled;
        public string MenuModNote;                       // why the menu improvements were skipped
        public List<string> Warnings = new List<string>();
    }

    /// <summary>
    /// The whole install, run on a worker thread: build tools, disc
    /// extraction, the recompiler (tools\regen.ps1), the CMake build, the
    /// menu mod (tools\mods\menus.py), and copying the game into place. The
    /// wizard polls Stage, Detail, Percent and LogLines.
    /// </summary>
    sealed class InstallJob
    {
        public const string ExeName = "RE-Amped2.exe";

        /// <summary>The game's files before the rename to RE-Amped2; an update removes them.</summary>
        public const string LegacyExeName = "Amped2.exe";
        static readonly string[] LegacyFiles = { LegacyExeName, "Amped2.ico", "amped2_recomp.pdb" };
        const string LegacyShortcut = "Amped 2.lnk";

        /// <summary>Whether <paramref name="dir"/> holds an install, under either name.</summary>
        public static bool IsInstalledIn(string dir) =>
            File.Exists(Path.Combine(dir, ExeName)) || File.Exists(Path.Combine(dir, LegacyExeName));

        public static readonly string[] StageTitles =
        {
            "Getting the build tools ready",
            "Copying the game from your disc image",
            "Preparing the recompiler",
            "Translating the game's code for Windows",
            "Compiling the game",
            "Adding the menu improvements",
            "Finishing up",
        };

        // Where each stage starts on the overall bar; compiling is the long one.
        static readonly double[] StageStart = { 0, 3, 12, 17, 40, 95, 98, 100 };

        public volatile int Stage = -1;
        public volatile string Detail = "";
        public readonly ConcurrentQueue<string> LogLines = new ConcurrentQueue<string>();
        public InstallResult Result { get; private set; }

        readonly InstallOptions _o;
        readonly CancellationTokenSource _cts = new CancellationTokenSource();
        readonly object _lock = new object();
        double _stageFraction;
        StreamWriter _log;
        string _logPath;
        Toolchain _tools;
        bool _menuPackages;

        public InstallJob(InstallOptions o) { _o = o; }

        public double Percent
        {
            get
            {
                lock (_lock)
                {
                    int s = Stage;
                    if (s < 0) return 0;
                    return StageStart[s] + (StageStart[s + 1] - StageStart[s]) * _stageFraction;
                }
            }
        }

        public void Cancel() => _cts.Cancel();

        CancellationToken Ct => _cts.Token;
        string Dest => _o.InstallDir;
        string GameDir => Path.Combine(Dest, "game");
        string DiscStaging => Path.Combine(Dest, "_disc_new");
        string Work => Path.Combine(Dest, "_install_temp");
        string Src => Path.Combine(Work, "src");
        string Amped2 => Path.Combine(Src, "amped2");
        string GameLink => Path.Combine(Amped2, "game");
        string BuildDir => Path.Combine(Amped2, "build");
        string VenvPython => Path.Combine(Work, @"venv\Scripts\python.exe");

        // ── Driver ───────────────────────────────────────────────────

        public void Run()
        {
            var clock = Stopwatch.StartNew();
            var r = new InstallResult { InstallDir = Dest };
            try
            {
                Directory.CreateDirectory(Dest);
                r.WasUpdate = IsInstalledIn(Dest);
                OpenLog();
                SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED);   // no sleep mid-build

                StageTools(r);
                StageExtract();
                StagePrepare();
                StageRecompile();
                StageBuild();
                StageMenuMod(r);
                StageFinish(r);
                r.Success = true;
                Log("Installation finished.");
            }
            catch (OperationCanceledException)
            {
                r.Cancelled = true;
                Log("Installation cancelled.");
            }
            catch (UserFacingException e)
            {
                r.Error = e.Message;
                r.Advice = e.Advice;
                Log("ERROR: " + e.Message + (e.InnerException != null ? "\n" + e.InnerException : ""));
            }
            catch (Exception e)
            {
                Explain(e, r);
                Log("ERROR: " + e);
            }
            finally
            {
                if (!r.Success && !r.Cancelled && Stage >= 0)
                    r.FailedStage = StageTitles[Stage];
                CleanUp(r);
                SetThreadExecutionState(ES_CONTINUOUS);
                r.Duration = clock.Elapsed;
                r.LogPath = _logPath;
                Log($"Took {r.Duration:hh\\:mm\\:ss}.");
                lock (_lock) { _log?.Dispose(); _log = null; }
                Result = r;
            }
        }

        void Begin(int stage, string detail = "")
        {
            lock (_lock)
            {
                Stage = stage;
                _stageFraction = 0;
            }
            Detail = detail;
            Log("");
            Log("== " + StageTitles[stage] + " ==");
        }

        void SetFraction(double f)
        {
            lock (_lock) _stageFraction = Math.Max(_stageFraction, Math.Min(1, f));
        }

        // ── Stages ───────────────────────────────────────────────────

        void StageTools(InstallResult r)
        {
            Begin(0, "Looking for the tools on this PC");
            _tools = Toolchain.Detect(_o.MenuMod);
            _tools = Toolchain.InstallMissing(_tools, _o.MenuMod, s => Detail = s, Log, Ct);
            Log($"Python:  {_tools.PythonExe} ({_tools.PythonVersion})");
            Log($"VS:      {_tools.VsName} at {_tools.VsPath}");
            Log($"CMake:   {_tools.CMakeExe} ({_tools.CMakeGenerator})");
            Log($"Java:    {_tools.JavaExe ?? "(none)"}");
            if (_o.MenuMod && _tools.JavaExe == null)
                r.MenuModNote = "Java couldn't be installed, so the menu improvements were left out.";
        }

        void StageExtract()
        {
            Begin(1, "Checking free space");
            var disc = _o.Disc;

            // xdvdfs only unpacks into a new folder, so the disc goes to
            // _disc_new and is merged into game\ afterwards. That also keeps
            // what the game wrote there (saves in game\UDATA) on an update.
            if (Directory.Exists(DiscStaging))
                Directory.Delete(DiscStaging, true);
            long need = disc.GameBytes + 2L * 1024 * 1024 * 1024;   // plus the build's working files
            long free = new DriveInfo(Path.GetPathRoot(Path.GetFullPath(Dest))).AvailableFreeSpace;
            if (free < need)
                throw new UserFacingException(
                    $"There isn't enough free space on drive {Path.GetPathRoot(Dest)}",
                    $"The install needs about {Gb(need)} free. Free some space, or choose another drive, and run the installer again.");

            // xdvdfs prints "Extracting file <out>\<path>" as it starts each file.
            var prefix = Norm(DiscStaging) + "\\";
            long done = 0;
            int files = 0;
            int code = ProcessRunner.Run(Payload.Xdvdfs,
                $"unpack {ProcessRunner.Quote(disc.IsoPath)} {ProcessRunner.Quote(DiscStaging)}", null, line =>
                {
                    LogQuiet(line);
                    if (!line.StartsWith("Extracting "))
                        Log(line);   // errors, shown in the details too
                    if (!line.StartsWith("Extracting file ")) return;
                    var path = Norm(line.Substring("Extracting file ".Length).Trim());
                    var rel = path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase) ? path.Substring(prefix.Length) : path;
                    files++;
                    if (disc.FileSizes.TryGetValue(rel, out long size)) done += size;
                    SetFraction(0.97 * (disc.GameBytes > 0 ? (double)done / disc.GameBytes : 0));
                    Detail = $"Copied {Math.Min(files, disc.FileCount)} of {disc.FileCount} files ({Gb(done)} of {Gb(disc.GameBytes)})";
                }, Ct);
            if (code != 0 || !File.Exists(Path.Combine(DiscStaging, "default.xbe")))
                throw new UserFacingException(
                    "The game files couldn't be copied from the disc image.",
                    "Check that the drive has enough free space and that the disc image isn't damaged, then try again.");
            Log($"Extracted {files} files, {Gb(done)}.");

            Ct.ThrowIfCancellationRequested();
            Detail = "Moving the game files into place";
            MergeMove(DiscStaging, GameDir);
            Directory.Delete(DiscStaging, true);
            SetFraction(1);
        }

        /// <summary>Moves every file under <paramref name="from"/> into <paramref name="to"/>, replacing same-named files and keeping the rest.</summary>
        static void MergeMove(string from, string to)
        {
            Directory.CreateDirectory(to);
            foreach (var f in Directory.GetFiles(from))
            {
                var target = Path.Combine(to, Path.GetFileName(f));
                if (File.Exists(target))
                {
                    File.SetAttributes(target, FileAttributes.Normal);
                    File.Delete(target);
                }
                File.Move(f, target);
            }
            foreach (var d in Directory.GetDirectories(from))
                MergeMove(d, Path.Combine(to, Path.GetFileName(d)));
        }

        void StagePrepare()
        {
            Begin(2, "Unpacking the recompiler");
            if (Directory.Exists(Work))
                RemoveWork();
            Payload.ExtractAll(Src, (d, t) => SetFraction(0.3 * d / t), Ct);
            Log("Sources: " + string.Join(", ", Payload.Manifest.Select(kv => kv.Key + "=" + kv.Value)));

            // The recompiler and the menu mod read game\ beside their sources;
            // a junction points that at the installed copy (removed in CleanUp).
            int code = ProcessRunner.Run(Path.Combine(Environment.SystemDirectory, "cmd.exe"),
                $"/c mklink /J {ProcessRunner.Quote(GameLink)} {ProcessRunner.Quote(GameDir)}", null, Log, Ct);
            if (code != 0 || !File.Exists(Path.Combine(GameLink, "default.xbe")))
                throw new UserFacingException("The installer couldn't set up its working folder.",
                    "Try a different install folder, for example one in your user folder.");
            SetFraction(0.35);

            Detail = "Setting up a private Python environment";
            code = ProcessRunner.Run(_tools.PythonExe, $"-m venv {ProcessRunner.Quote(Path.Combine(Work, "venv"))}",
                                     Work, Log, Ct, PythonEnv());
            if (code != 0 || !File.Exists(VenvPython))
                throw new UserFacingException("Python couldn't set up the recompiler's environment.",
                    "Reinstalling Python (64-bit, 3.10 or newer) from python.org usually fixes this.");
            SetFraction(0.5);

            Detail = "Downloading the recompiler's Python packages";
            code = Pip("\"capstone>=5.0,<6\"");
            if (code != 0)
                throw new UserFacingException("The recompiler's Python packages couldn't be downloaded.",
                    "Check your internet connection, then run the installer again.");
            SetFraction(0.8);

            if (_o.MenuMod && _tools.JavaExe != null)
            {
                Detail = "Downloading the menu tools' Python packages";
                _menuPackages = Pip("numpy pillow") == 0;
            }
            SetFraction(1);
        }

        int Pip(string packages) =>
            ProcessRunner.Run(VenvPython, "-m pip install --disable-pip-version-check --no-input --progress-bar off " + packages,
                              Work, Log, Ct, PythonEnv());

        void StageRecompile()
        {
            Begin(3, "Reading the game's program file");
            // regen.ps1's step banners, where each starts within this stage,
            // and what the player is told meanwhile.
            var steps = new (string Banner, double At, string Text)[]
            {
                // Shares measured on a 16-core PC: disassembly ~30%, C output ~65%.
                ("=== Step 2:",   0.00, "Reading the game's program file"),
                ("=== Step 3:",   0.01, "Finding every function in the game's code"),
                ("=== Step 4:",   0.31, "Recognising Microsoft's library code"),
                ("=== Step 4.5:", 0.33, "Working out how the functions call each other"),
                ("=== Step 4.6:", 0.34, "Naming known functions"),
                ("=== Step 5:",   0.35, "Writing the game's code as C (about 15,000 functions)"),
            };
            int current = 0;
            double frac = 0;
            var regen = Path.Combine(Amped2, @"tools\regen.ps1");
            int code = ProcessRunner.Run(PowerShellExe,
                $"-NoProfile -ExecutionPolicy Bypass -File {ProcessRunner.Quote(regen)} -Python {ProcessRunner.Quote(VenvPython)}",
                Amped2, line =>
                {
                    Log(line);
                    for (int i = 0; i < steps.Length; i++)
                        if (line.StartsWith(steps[i].Banner))
                        {
                            current = i;
                            frac = steps[i].At;
                            Detail = steps[i].Text;
                        }
                    // Creep towards the next step so the bar keeps moving.
                    double next = current + 1 < steps.Length ? steps[current + 1].At : 1.0;
                    frac += (next - 0.005 - frac) * 0.003;
                    SetFraction(frac);
                }, Ct, PythonEnv());
            var gen = Path.Combine(Amped2, @"src\recomp\gen");
            if (code != 0 || !Directory.Exists(gen) || Directory.GetFiles(gen, "recomp_*.c").Length == 0)
                throw new UserFacingException("The game's code couldn't be translated.",
                    "This shouldn't happen with a good disc image. Please share the install log with the community on Patreon so it can be looked at.");
        }

        void StageBuild()
        {
            Begin(4, "Setting up the build");
            var gen = Path.Combine(Amped2, @"src\recomp\gen");
            int total = Directory.GetFiles(gen, "*.c").Length
                        + Directory.GetFiles(Path.Combine(Src, @"xboxrecomp\src"), "*.c", SearchOption.AllDirectories).Length
                        + 3;
            var env = new Dictionary<string, string>
            {
                ["VSLANG"] = "1033",                    // English compiler messages in the log
                ["MSBUILDDISABLENODEREUSE"] = "1",      // no idle MSBuild nodes holding the work folder
            };

            int code = ProcessRunner.Run(_tools.CMakeExe,
                $"-S {ProcessRunner.Quote(Amped2)} -B {ProcessRunner.Quote(BuildDir)} -G {ProcessRunner.Quote(_tools.CMakeGenerator)} -A x64 " +
                $"-DCMAKE_GENERATOR_INSTANCE={ProcessRunner.Quote(_tools.VsPath)} -DAMPED2_MP_JOBS={CompileJobs()}",
                Amped2, Log, Ct, env);
            if (code != 0)
                throw new UserFacingException("The build couldn't be set up.",
                    "Microsoft's C++ build tools may be incomplete. Open the Visual Studio Installer, check that " +
                    "\"Desktop development with C++\" is installed, then run this installer again.");
            SetFraction(0.02);

            var compiled = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var errors = new List<string>();
            var source = new Regex(@"^\s{1,4}([\w\-.]+\.c)\s*$");
            var error = new Regex(@"\b(fatal error|error) [A-Z]+\d+");
            Detail = $"Compiled 0 of {total} code files";
            code = ProcessRunner.Run(_tools.CMakeExe,
                $"--build {ProcessRunner.Quote(BuildDir)} --config Release --parallel", Amped2, line =>
                {
                    Log(line);
                    var m = source.Match(line);
                    if (m.Success && compiled.Add(m.Groups[1].Value))
                    {
                        int n = Math.Min(compiled.Count, total);
                        SetFraction(0.02 + 0.93 * n / total);
                        Detail = n >= total - 2
                            ? "Putting the pieces together"
                            : $"Compiled {n} of {total} code files";
                    }
                    if (error.IsMatch(line) && errors.Count < 10)
                        errors.Add(line.Trim());
                }, Ct, env);
            var exe = Path.Combine(BuildDir, "Release", ExeName);
            if (code != 0 || !File.Exists(exe))
            {
                if (errors.Count > 0)
                    Log("First errors:\n  " + string.Join("\n  ", errors));
                throw new UserFacingException("The game couldn't be compiled.",
                    "The install log has the details. Please share it with the community on Patreon so it can be fixed.");
            }
            SetFraction(1);
        }

        void StageMenuMod(InstallResult r)
        {
            if (!_o.MenuMod)
                return;
            Begin(5, "Editing the menus");
            if (_tools.JavaExe == null)
                return;   // MenuModNote already says why
            if (!_menuPackages)
            {
                r.MenuModNote = "The menu tools couldn't be downloaded, so the menu improvements were left out.";
                return;
            }

            var env = PythonEnv();
            env["PATH"] = Path.GetDirectoryName(_tools.JavaExe) + ";" + Environment.GetEnvironmentVariable("PATH");
            double frac = 0;
            int code = ProcessRunner.Run(VenvPython, ProcessRunner.Quote(Path.Combine(Amped2, @"tools\mods\menus.py")),
                Amped2, line =>
                {
                    Log(line);
                    frac += (0.9 - frac) * 0.05;
                    SetFraction(frac);
                }, Ct, env);
            var built = Path.Combine(Amped2, @"mods\build\game");
            if (code != 0 || !Directory.Exists(built))
            {
                r.MenuModNote = "The menu improvements couldn't be added (the install log has the details).";
                return;
            }

            var target = Path.Combine(Dest, @"mods\build\game");
            if (Directory.Exists(target))
                Directory.Delete(target, true);
            CopyDirectory(built, target);
            r.MenuModInstalled = true;
            SetFraction(1);
        }

        void StageFinish(InstallResult r)
        {
            Begin(6, "Copying the game into place");
            var exe = Path.Combine(Dest, ExeName);
            try
            {
                File.Copy(Path.Combine(BuildDir, "Release", ExeName), exe, true);
            }
            catch (IOException e) when (IsLocked(e))
            {
                throw new UserFacingException("RE-Amped2 is still running.", "Close the game, then run the installer again.", e);
            }
            // The crash handler names guest functions from the .pdb, found by
            // the name the linker recorded.
            var pdbName = Path.ChangeExtension(ExeName, ".pdb");
            var pdb = Path.Combine(BuildDir, "Release", pdbName);
            if (File.Exists(pdb))
                File.Copy(pdb, Path.Combine(Dest, pdbName), true);
            foreach (var old in LegacyFiles)
                TryDelete(Path.Combine(Dest, old));
            r.ExePath = exe;

            var icon = Path.Combine(Dest, "RE-Amped2.ico");
            using (var s = typeof(InstallJob).Assembly.GetManifestResourceStream("RE-Amped2.ico"))
            using (var f = File.Create(icon))
                s.CopyTo(f);

            TryDelete(Path.Combine(GameDir, "default_analysis.json"));   // written by the recompiler
            WriteReadme();
            WriteInstallInfo();
            SetFraction(0.6);

            if (_o.DesktopShortcut)
            {
                Detail = "Creating the desktop shortcut";
                try
                {
                    var desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
                    Shortcut.Create(Path.Combine(desktop, "RE-Amped2.lnk"), exe, Dest, icon, "RE-Amped2");
                    TryDelete(Path.Combine(desktop, LegacyShortcut));   // pointed at the old exe
                    r.ShortcutCreated = true;
                }
                catch (Exception e)
                {
                    Log("Shortcut failed: " + e);
                    r.Warnings.Add("The desktop shortcut couldn't be created. Start the game with " + ExeName + " in the install folder.");
                }
            }
            SetFraction(1);
        }

        // ── Files ────────────────────────────────────────────────────

        void WriteReadme()
        {
            var text = new StringBuilder()
                .AppendLine("RE-AMPED2: Amped 2 for Windows")
                .AppendLine("==============================")
                .AppendLine()
                .AppendLine("Start the game with RE-Amped2.exe (or the desktop shortcut).")
                .AppendLine()
                .AppendLine("Controls")
                .AppendLine("  An Xbox-style controller works out of the box.")
                .AppendLine("  Keyboard: arrow keys = d-pad, Z X A S = A B X Y, Enter = Start,")
                .AppendLine("  Backspace = Back, Q/E = white/black, 1/3 = triggers,")
                .AppendLine("  number pad = left stick, I J K L = right stick.")
                .AppendLine("  F11 or Alt+Enter switches between window and full screen.")
                .AppendLine("  F3 shows the frame rate.")
                .AppendLine()
                .AppendLine("Settings")
                .AppendLine("  Options > Game Options has WINDOW and RESOLUTION (with the menu improvements).")
                .AppendLine("  amped2.ini in this folder holds every setting; it is created the first time")
                .AppendLine("  the game starts. Remove the ; in front of a line to use it.")
                .AppendLine()
                .AppendLine("Your saves")
                .AppendLine("  Career progress is saved in game\\UDATA in this folder. Back it up before")
                .AppendLine("  deleting the folder. Running the installer again keeps it.")
                .AppendLine()
                .AppendLine("Community, support and updates")
                .AppendLine("  " + Links.Patreon);
            File.WriteAllText(Path.Combine(Dest, "README.txt"), text.ToString(), Encoding.UTF8);
        }

        void WriteInstallInfo()
        {
            var lines = new List<string>
            {
                "installed=" + DateTime.Now.ToString("yyyy-MM-dd HH:mm"),
                "disc=" + _o.Disc.RegionName,
                "image=" + _o.Disc.IsoPath,
                "installer=" + typeof(InstallJob).Assembly.GetName().Version,
            };
            lines.AddRange(Payload.Manifest.Select(kv => kv.Key + "=" + kv.Value));
            File.WriteAllLines(Path.Combine(Dest, "install-info.txt"), lines);
        }

        /// <summary>
        /// Removes the working folder. The game\ junction inside it is
        /// unlinked first, on its own, so the delete can never reach the
        /// installed game files (or the saves in game\UDATA) through it.
        /// </summary>
        void RemoveWork()
        {
            if (Directory.Exists(GameLink))
            {
                var attrs = File.GetAttributes(GameLink);
                if ((attrs & FileAttributes.ReparsePoint) == 0)
                    throw new IOException("Unexpected real folder at " + GameLink);
                Directory.Delete(GameLink, false);     // removes the link, not its target
            }
            if (Directory.Exists(GameLink))
                throw new IOException("Could not unlink " + GameLink);
            // A just-killed compiler can hold its files for a moment.
            for (int attempt = 1; ; attempt++)
            {
                try
                {
                    Directory.Delete(Work, true);
                    return;
                }
                catch (IOException) when (attempt < 5) { Thread.Sleep(1000); }
                catch (UnauthorizedAccessException) when (attempt < 5)
                {
                    // Read-only files (the junction is gone, so this stays inside Work).
                    foreach (var f in Directory.EnumerateFiles(Work, "*", SearchOption.AllDirectories))
                        try { File.SetAttributes(f, FileAttributes.Normal); } catch (Exception) { }
                    Thread.Sleep(1000);
                }
            }
        }

        void CleanUp(InstallResult r)
        {
            try
            {
                if (Directory.Exists(DiscStaging))
                    Directory.Delete(DiscStaging, true);
                if (Directory.Exists(Work))
                {
                    Detail = "Removing temporary files";
                    RemoveWork();
                }
            }
            catch (Exception e)
            {
                Log("Could not remove the working folder " + Work + ": " + e.Message);
                r.Warnings.Add($"Some temporary files couldn't be removed. You can delete the folder {Work} yourself.");
            }
        }

        static void CopyDirectory(string from, string to)
        {
            Directory.CreateDirectory(to);
            foreach (var f in Directory.GetFiles(from))
                File.Copy(f, Path.Combine(to, Path.GetFileName(f)), true);
            foreach (var d in Directory.GetDirectories(from))
                CopyDirectory(d, Path.Combine(to, Path.GetFileName(d)));
        }

        static void TryDelete(string path)
        {
            try { if (File.Exists(path)) File.Delete(path); } catch (Exception) { }
        }

        // ── Logging and helpers ──────────────────────────────────────

        void OpenLog()
        {
            _logPath = Path.Combine(Dest, "install.log");
            try
            {
                _log = new StreamWriter(_logPath, false, Encoding.UTF8) { AutoFlush = true };
            }
            catch (Exception)
            {
                _logPath = Path.Combine(Path.GetTempPath(), "RE-Amped2-install.log");
                _log = new StreamWriter(_logPath, false, Encoding.UTF8) { AutoFlush = true };
            }
            Log($"RE-Amped2 installer {typeof(InstallJob).Assembly.GetName().Version}, {DateTime.Now:yyyy-MM-dd HH:mm:ss}");
            Log($"Windows {Environment.OSVersion.Version}, {Environment.ProcessorCount} cores, {TotalRamGb():0.#} GB RAM");
            Log($"Disc image: {_o.Disc.IsoPath} ({_o.Disc.Title}, {_o.Disc.RegionName})");
            Log($"Install to: {Dest}  shortcut={_o.DesktopShortcut} menus={_o.MenuMod}");
        }

        void Log(string line)
        {
            LogQuiet(line);
            LogLines.Enqueue(line);
        }

        /// <summary>To the log file only (xdvdfs's per-file lines).</summary>
        void LogQuiet(string line)
        {
            lock (_lock)
                _log?.WriteLine($"[{DateTime.Now:HH:mm:ss}] {line}");
        }

        Dictionary<string, string> PythonEnv() => new Dictionary<string, string>
        {
            ["PYTHONUNBUFFERED"] = "1",
            ["PYTHONUTF8"] = "1",
            ["PYTHONIOENCODING"] = "utf-8",
            ["PIP_DISABLE_PIP_VERSION_CHECK"] = "1",
        };

        static string PowerShellExe => Path.Combine(Environment.SystemDirectory, @"WindowsPowerShell\v1.0\powershell.exe");

        /// <summary>Parallel compiler jobs for the generated chunks: one per core, about 3 GB of RAM each, 2 to 8.</summary>
        static int CompileJobs()
        {
            int byRam = (int)(TotalRamGb() / 3);
            return Math.Max(2, Math.Min(8, Math.Min(Environment.ProcessorCount, byRam)));
        }

        static void Explain(Exception e, InstallResult r)
        {
            int hr = Marshal.GetHRForException(e);
            if (e is IOException && (hr == unchecked((int)0x80070070) || hr == unchecked((int)0x80070027)))
            {
                r.Error = "The drive ran out of space.";
                r.Advice = "Free some space (the game needs about 6 GB while installing), then run the installer again.";
            }
            else if (e is UnauthorizedAccessException)
            {
                r.Error = "The installer isn't allowed to write to the install folder.";
                r.Advice = "Choose a folder you own, such as C:\\Games\\RE-Amped2 or one in your user folder.";
            }
            else
            {
                r.Error = "Something unexpected went wrong: " + e.Message;
                r.Advice = "The install log has the details. Please share it with the community on Patreon.";
            }
        }

        static bool IsLocked(IOException e)
        {
            int hr = Marshal.GetHRForException(e);
            return hr == unchecked((int)0x80070020) || hr == unchecked((int)0x80070021);
        }

        static string Norm(string path) => path.Replace('/', '\\').TrimEnd('\\');

        public static string Gb(long bytes) => (bytes / 1073741824.0).ToString("0.0") + " GB";

        public static double TotalRamGb()
        {
            var m = new MEMORYSTATUSEX { dwLength = (uint)Marshal.SizeOf(typeof(MEMORYSTATUSEX)) };
            return GlobalMemoryStatusEx(ref m) ? m.ullTotalPhys / 1073741824.0 : 8;
        }

        const uint ES_CONTINUOUS = 0x80000000, ES_SYSTEM_REQUIRED = 0x00000001;

        [DllImport("kernel32.dll")]
        static extern uint SetThreadExecutionState(uint flags);

        [StructLayout(LayoutKind.Sequential)]
        struct MEMORYSTATUSEX
        {
            public uint dwLength, dwMemoryLoad;
            public ulong ullTotalPhys, ullAvailPhys, ullTotalPageFile, ullAvailPageFile,
                         ullTotalVirtual, ullAvailVirtual, ullAvailExtendedVirtual;
        }

        [DllImport("kernel32.dll", SetLastError = true)]
        static extern bool GlobalMemoryStatusEx(ref MEMORYSTATUSEX m);
    }
}
