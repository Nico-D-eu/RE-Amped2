using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Text;
using System.Threading;

namespace Amped2Installer
{
    /// <summary>
    /// Runs a console tool without a window, hands every line it prints
    /// (stdout and stderr) to a callback, and kills its whole process tree
    /// when the install is cancelled.
    /// </summary>
    static class ProcessRunner
    {
        public static int Run(string exe, string args, string workDir, Action<string> onLine,
                              CancellationToken ct, IDictionary<string, string> env = null)
        {
            var psi = new ProcessStartInfo(exe, args)
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8,
                StandardErrorEncoding = Encoding.UTF8,
                WorkingDirectory = workDir ?? Environment.CurrentDirectory,
            };
            if (env != null)
                foreach (var kv in env)
                    psi.EnvironmentVariables[kv.Key] = kv.Value;

            using (var p = new Process { StartInfo = psi })
            {
                p.OutputDataReceived += (s, e) => { if (e.Data != null) onLine?.Invoke(e.Data); };
                p.ErrorDataReceived += (s, e) => { if (e.Data != null) onLine?.Invoke(e.Data); };
                p.Start();
                p.BeginOutputReadLine();
                p.BeginErrorReadLine();
                using (ct.Register(() => KillTree(p)))
                    p.WaitForExit();   // the overload without a timeout also drains the output
                ct.ThrowIfCancellationRequested();
                return p.ExitCode;
            }
        }

        /// <summary>Runs a quick probe and returns its output, or null if it could not start.</summary>
        public static string Capture(string exe, string args, out int exitCode, int timeoutMs = 30000)
        {
            exitCode = -1;
            try
            {
                var sb = new StringBuilder();
                var psi = new ProcessStartInfo(exe, args)
                {
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                };
                using (var p = new Process { StartInfo = psi })
                {
                    p.OutputDataReceived += (s, e) => { if (e.Data != null) lock (sb) sb.AppendLine(e.Data); };
                    p.ErrorDataReceived += (s, e) => { if (e.Data != null) lock (sb) sb.AppendLine(e.Data); };
                    p.Start();
                    p.BeginOutputReadLine();
                    p.BeginErrorReadLine();
                    if (!p.WaitForExit(timeoutMs))
                    {
                        KillTree(p);
                        return null;
                    }
                    p.WaitForExit();
                    exitCode = p.ExitCode;
                    lock (sb) return sb.ToString();
                }
            }
            catch (Exception)
            {
                return null;
            }
        }

        static void KillTree(Process p)
        {
            try
            {
                if (p.HasExited)
                    return;
                using (var k = Process.Start(new ProcessStartInfo("taskkill.exe", $"/PID {p.Id} /T /F")
                       { UseShellExecute = false, CreateNoWindow = true }))
                    k?.WaitForExit(10000);
            }
            catch (Exception)
            {
                try { p.Kill(); } catch (Exception) { }
            }
        }

        public static string Quote(string arg)
        {
            if (string.IsNullOrEmpty(arg))
                return "\"\"";
            if (arg.IndexOfAny(new[] { ' ', '\t', '"' }) < 0)
                return arg;
            // A trailing backslash would escape the closing quote.
            return "\"" + arg.Replace("\"", "\\\"").TrimEnd('\\') + (arg.EndsWith("\\") ? "\\\\" : "") + "\"";
        }
    }
}
