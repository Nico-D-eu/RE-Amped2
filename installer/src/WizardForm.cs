using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Microsoft.Win32;

namespace Amped2Installer
{
    /// <summary>
    /// The four-step wizard: 1 disc image, 2 install folder and options,
    /// 3 install (InstallJob on a worker thread), 4 result and where to report problems.
    /// </summary>
    sealed class WizardForm : Form
    {
        // ── Look ─────────────────────────────────────────────────────
        // From the RE-Amped2 art: the banner's night blue and the logo's glow.
        static readonly Color Navy = Color.FromArgb(0x06, 0x12, 0x28);
        static readonly Color NavyLight = Color.FromArgb(0x0C, 0x26, 0x4E);
        static readonly Color HeaderSub = Color.FromArgb(0xA8, 0xD4, 0xFF);
        static readonly Color Glow = Color.FromArgb(0x46, 0xB4, 0xFF);
        static readonly Color Accent = Color.FromArgb(0x16, 0x7E, 0xE6);
        static readonly Color Ink = Color.FromArgb(0x1B, 0x27, 0x33);
        static readonly Color Body = Color.FromArgb(0x3C, 0x4A, 0x57);
        static readonly Color Muted = Color.FromArgb(0x6B, 0x7A, 0x88);
        static readonly Color Good = Color.FromArgb(0x1E, 0x8E, 0x4F);
        static readonly Color Bad = Color.FromArgb(0xC6, 0x28, 0x28);
        static readonly Color Info = Color.FromArgb(0x1E, 0x6F, 0xB8);
        static readonly Color FeedbackBg = Color.FromArgb(0xEE, 0xF5, 0xFD);
        static readonly Color FeedbackBorder = Color.FromArgb(0xC7, 0xDD, 0xF5);
        static readonly Color FooterBg = Color.FromArgb(0xF4, 0xF6, 0xF8);
        static readonly Color Border = Color.FromArgb(0xDD, 0xE3, 0xE9);

        readonly Font _base = new Font("Segoe UI", 9.75f);
        readonly Font _bold = new Font("Segoe UI Semibold", 9.75f);
        readonly Font _h1 = new Font("Segoe UI Semibold", 15f);
        readonly Font _small = new Font("Segoe UI", 8.75f);
        readonly Font _mono = new Font("Consolas", 8.5f);

        const string RegKey = @"Software\REAmped2\Amped 2";

        // ── Chrome ───────────────────────────────────────────────────
        readonly Panel _header, _body, _footer;
        readonly Label[] _stepLabels = new Label[4];
        readonly Button _back, _next, _cancel;
        readonly Label _version;
        readonly LinkLabel _licenses;
        readonly Image _headerArt, _badge;
        readonly Panel[] _pages = new Panel[4];
        int _page;

        // ── Page 1: disc image ───────────────────────────────────────
        TextBox _isoBox;
        Label _isoStatus, _isoAdvice;
        DiscInfo _disc;
        bool _checkingIso;

        // ── Page 2: location ─────────────────────────────────────────
        TextBox _dirBox;
        Label _spaceLabel, _existingLabel, _toolsNote, _timeNote;
        CheckBox _shortcutBox, _menuBox, _lookBox;
        TableLayoutPanel _toolsList;
        LinkLabel _recheck;
        Toolchain _tools;
        bool _detecting;

        // ── Page 3: install ──────────────────────────────────────────
        readonly List<(Label Mark, Label Title, int Stage)> _stageRows = new List<(Label, Label, int)>();
        TableLayoutPanel _stageTable;
        ProgressBar _bar;
        Label _detail, _elapsed, _installIntro;
        LinkLabel _detailsToggle;
        TextBox _logBox;
        InstallJob _job;
        Thread _jobThread;
        readonly System.Windows.Forms.Timer _timer = new System.Windows.Forms.Timer { Interval = 200 };
        readonly Stopwatch _clock = new Stopwatch();
        bool _closeWhenStopped;

        // ── Page 4: done ─────────────────────────────────────────────
        TableLayoutPanel _donePage;
        CheckBox _launchBox;

        public WizardForm()
        {
            SuspendLayout();
            Text = "RE-Amped2 Installer";
            Font = _base;
            BackColor = Color.White;
            FormBorderStyle = FormBorderStyle.FixedSingle;
            MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen;
            ClientSize = new Size(800, 650);   // the header art is 140 tall
            try
            {
                using (var s = typeof(WizardForm).Assembly.GetManifestResourceStream("RE-Amped2.ico"))
                    if (s != null) Icon = new Icon(s);
            }
            catch (Exception) { }

            _headerArt = LoadImage("header.jpg");
            _badge = LoadImage("badge.png");

            // Header: the RE-Amped2 art (logo on the left; PaintHeader adds the
            // early-access tag and subtitle under it), the four steps on the right.
            _header = new DoubleBufferedPanel { Dock = DockStyle.Top, Height = 140 };
            _header.Paint += PaintHeader;
            var steps = new FlowLayoutPanel
            {
                AutoSize = true,
                WrapContents = false,
                BackColor = Color.Transparent,
                Anchor = AnchorStyles.Top | AnchorStyles.Right,
            };
            string[] names = { "Disc", "Location", "Install", "Done" };
            for (int i = 0; i < 4; i++)
            {
                _stepLabels[i] = new Label
                {
                    Text = $"{i + 1}  {names[i]}",
                    AutoSize = true,
                    BackColor = Color.Transparent,
                    Margin = new Padding(10, 0, 4, 0),
                    Padding = new Padding(2, 4, 2, 6),
                };
                _stepLabels[i].Paint += PaintStepUnderline;
                steps.Controls.Add(_stepLabels[i]);
            }
            _header.Controls.Add(steps);
            _header.Layout += (s, e) =>
                steps.Location = new Point(_header.ClientSize.Width - steps.Width - 22,
                                           (_header.ClientSize.Height - steps.Height) / 2);

            // Footer: Back / Next / Cancel.
            _footer = new Panel { Dock = DockStyle.Bottom, Height = 56, BackColor = FooterBg };
            _footer.Paint += (s, e) => { using (var p = new Pen(Border)) e.Graphics.DrawLine(p, 0, 0, _footer.Width, 0); };
            var buttons = new FlowLayoutPanel
            {
                Dock = DockStyle.Right,
                FlowDirection = FlowDirection.RightToLeft,
                AutoSize = true,
                WrapContents = false,
                Padding = new Padding(0, 12, 16, 0),
                BackColor = FooterBg,
            };
            _cancel = MakeButton("Cancel", false);
            _next = MakeButton("Next", true);
            _back = MakeButton("Back", false);
            _cancel.Margin = new Padding(14, 0, 0, 0);
            buttons.Controls.AddRange(new Control[] { _cancel, _next, _back });
            _version = new Label
            {
                Text = "v" + typeof(WizardForm).Assembly.GetName().Version.ToString(3) + " · Early Access",
                ForeColor = Muted,
                Font = _small,
                AutoSize = true,
                Location = new Point(18, 20),
                BackColor = FooterBg,
            };
            // The licence texts (RE-Amped2, the toolkit, xdvdfs, unluac), from the payload.
            _licenses = new LinkLabel { Text = "Licences", Font = _small, AutoSize = true, BackColor = FooterBg };
            _licenses.LinkClicked += (s, e) => ShowLicenses();
            _footer.Controls.Add(buttons);
            _footer.Controls.Add(_version);
            _footer.Controls.Add(_licenses);
            _footer.Layout += (s, e) => _licenses.Location = new Point(_version.Right + 12, _version.Top);

            _body = new Panel { Dock = DockStyle.Fill, BackColor = Color.White };
            _pages[0] = BuildDiscPage();
            _pages[1] = BuildLocationPage();
            _pages[2] = BuildInstallPage();
            _pages[3] = BuildDonePage();
            foreach (var p in _pages)
            {
                p.Visible = false;
                _body.Controls.Add(p);
            }

            Controls.Add(_body);
            Controls.Add(_footer);
            Controls.Add(_header);

            _back.Click += (s, e) => GoBack();
            _next.Click += (s, e) => GoNext();
            _cancel.Click += (s, e) => CancelClicked();
            _timer.Tick += (s, e) => PollJob();

            AllowDrop = true;
            DragEnter += (s, e) =>
            {
                if (_page == 0 && DroppedImage(e) != null) e.Effect = DragDropEffects.Copy;
            };
            DragDrop += (s, e) =>
            {
                var file = DroppedImage(e);
                if (_page == 0 && file != null) CheckImage(file);
            };

            AutoScaleDimensions = new SizeF(96f, 96f);
            AutoScaleMode = AutoScaleMode.Dpi;
            ResumeLayout(false);
            PerformLayout();
            ShowPage(0);
        }

        // ── Page 1 ───────────────────────────────────────────────────

        Panel BuildDiscPage()
        {
            var page = NewPage();
            Add(page, Heading("Choose your Amped 2 disc image"));
            Add(page, Para("This installer turns your own copy of Amped 2 for the original Xbox into a game that runs " +
                           "natively on Windows. Pick the disc image (.iso or .xiso) you made from your disc. " +
                           "The USA and the European release both work."));

            var row = Row(out _isoBox, "Browse\u2026", BrowseIso);
            _isoBox.ReadOnly = true;
            _isoBox.BackColor = Color.White;
            Add(page, row);

            _isoStatus = Para("", Muted);
            _isoStatus.Font = _bold;
            _isoStatus.Margin = new Padding(0, 10, 0, 2);
            Add(page, _isoStatus);
            _isoAdvice = Para("", Body);
            Add(page, _isoAdvice);

            AddFill(page);
            Add(page, Para("Early access: RE-Amped2 is a work in progress, so expect bugs and rough edges. " +
                           "Tell us what you run into on GitHub; the last page has the link.", Body, _small));
            Add(page, Para("No game files come with this installer: it needs your own legally owned copy of the game. " +
                           "You can also drag the disc image onto this window.", Muted, _small));
            return Wrap(page);
        }

        public void Preselect(string isoPath) => CheckImage(isoPath);

        void BrowseIso()
        {
            using (var dlg = new OpenFileDialog
            {
                Title = "Choose your Amped 2 disc image",
                Filter = "Xbox disc images (*.iso;*.xiso)|*.iso;*.xiso|All files (*.*)|*.*",
                CheckFileExists = true,
            })
            {
                if (!string.IsNullOrEmpty(_isoBox.Text))
                    try { dlg.InitialDirectory = Path.GetDirectoryName(_isoBox.Text); } catch (Exception) { }
                if (dlg.ShowDialog(this) == DialogResult.OK)
                    CheckImage(dlg.FileName);
            }
        }

        static string DroppedImage(DragEventArgs e)
        {
            if (!(e.Data.GetData(DataFormats.FileDrop) is string[] files) || files.Length != 1) return null;
            var ext = Path.GetExtension(files[0]).ToLowerInvariant();
            return ext == ".iso" || ext == ".xiso" ? files[0] : null;
        }

        void CheckImage(string path)
        {
            if (_checkingIso) return;
            _isoBox.Text = path;
            _disc = null;
            _checkingIso = true;
            _isoStatus.ForeColor = Muted;
            _isoStatus.Text = "Checking the disc image\u2026";
            _isoAdvice.Text = "";
            UpdateButtons();

            Task.Run(() => DiscImage.Inspect(path)).ContinueWith(t =>
            {
                _checkingIso = false;
                if (t.Exception == null)
                {
                    _disc = t.Result;
                    _isoStatus.ForeColor = Good;
                    _isoStatus.Text = $"\u2714  Amped 2 ({_disc.RegionName}) \u2014 {_disc.FileCount} files, {InstallJob.Gb(_disc.GameBytes)}";
                    _isoAdvice.Text = "Looks good. Click Next to choose where to install it.";
                }
                else
                {
                    var e = t.Exception.GetBaseException();
                    _isoStatus.ForeColor = Bad;
                    _isoStatus.Text = "\u2716  " + e.Message;
                    _isoAdvice.Text = (e as UserFacingException)?.Advice ?? "";
                }
                UpdateButtons();
            }, TaskScheduler.FromCurrentSynchronizationContext());
        }

        // ── Page 2 ───────────────────────────────────────────────────

        Panel BuildLocationPage()
        {
            var page = NewPage();
            Add(page, Heading("Where should RE-Amped2 go?"));
            Add(page, Para("Choose a folder you own. The game keeps its saves and settings in this folder, " +
                           "so folders inside Program Files won't work."));

            Add(page, Row(out _dirBox, "Browse\u2026", BrowseDir));
            _dirBox.Text = DefaultInstallDir();
            _dirBox.TextChanged += (s, e) => UpdateSpace();

            _spaceLabel = Para("", Muted, _small);
            _spaceLabel.Margin = new Padding(0, 4, 0, 0);
            Add(page, _spaceLabel);
            _existingLabel = Para("", Info, _small);
            _existingLabel.Margin = new Padding(0, 2, 0, 6);
            _existingLabel.Visible = false;   // takes no room unless there is an install to update
            Add(page, _existingLabel);

            _shortcutBox = new CheckBox { Text = "Create a desktop shortcut", Checked = true, AutoSize = true, Margin = new Padding(0, 6, 0, 2) };
            Add(page, _shortcutBox);
            _menuBox = new CheckBox
            {
                Text = "Add the RE-Amped2 menus (Quit Game, Window and Resolution settings, a Mods screen, no button hints)",
                Checked = true,
                AutoSize = true,
                Margin = new Padding(0, 2, 0, 12),
            };
            _menuBox.CheckedChanged += (s, e) => { ShowTools(); UpdateButtons(); };
            Add(page, _menuBox);
            _lookBox = new CheckBox
            {
                Text = "Use the RE-Amped2 look (new logo, start-up splash and loading screen)",
                Checked = true,
                AutoSize = true,
                Margin = new Padding(0, 0, 0, 12),
            };
            Add(page, _lookBox);
            _menuBox.Margin = new Padding(0, 2, 0, 2);

            var toolsHead = new TableLayoutPanel { ColumnCount = 2, AutoSize = true, Anchor = AnchorStyles.Left | AnchorStyles.Right, Margin = new Padding(0, 4, 0, 4) };
            toolsHead.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            toolsHead.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            toolsHead.Controls.Add(new Label { Text = "Free tools needed to build the game", Font = _bold, ForeColor = Ink, AutoSize = true, Margin = new Padding(0) }, 0, 0);
            _recheck = new LinkLabel { Text = "Check again", AutoSize = true, Margin = new Padding(0), Visible = false };
            _recheck.LinkClicked += (s, e) => DetectTools();
            toolsHead.Controls.Add(_recheck, 1, 0);
            Add(page, toolsHead);

            _toolsList = new TableLayoutPanel { ColumnCount = 2, AutoSize = true, Anchor = AnchorStyles.Left | AnchorStyles.Right, Margin = new Padding(0, 0, 0, 6) };
            _toolsList.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 26));
            _toolsList.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            Add(page, _toolsList);

            _toolsNote = Para("", Muted, _small);
            Add(page, _toolsNote);

            AddFill(page);
            _timeNote = Para(TimeNote(null), Muted, _small);
            Add(page, _timeNote);
            return Wrap(page);
        }

        static string DefaultInstallDir()
        {
            try
            {
                using (var k = Registry.CurrentUser.OpenSubKey(RegKey))
                    if (k?.GetValue("InstallDir") is string previous && previous.Length > 0)
                        return previous;
            }
            catch (Exception) { }
            return Path.Combine(Path.GetPathRoot(Environment.SystemDirectory), @"Games\RE-Amped2");
        }

        void BrowseDir()
        {
            using (var dlg = new FolderBrowserDialog
            {
                Description = "Choose the folder to install RE-Amped2 in. A folder named \"RE-Amped2\" is created inside it.",
                ShowNewFolderButton = true,
            })
            {
                try
                {
                    var current = _dirBox.Text;
                    while (!string.IsNullOrEmpty(current) && !Directory.Exists(current))
                        current = Path.GetDirectoryName(current);
                    if (!string.IsNullOrEmpty(current)) dlg.SelectedPath = current;
                }
                catch (Exception) { }
                if (dlg.ShowDialog(this) != DialogResult.OK) return;
                var chosen = dlg.SelectedPath;
                // Picking C:\Games means C:\Games\RE-Amped2, unless it already is one
                // (or an "Amped 2" folder from before the rename).
                if (!InstallJob.IsInstalledIn(chosen) &&
                    Path.GetFileName(chosen.TrimEnd('\\')).IndexOf("Amped", StringComparison.OrdinalIgnoreCase) < 0)
                    chosen = Path.Combine(chosen, "RE-Amped2");
                _dirBox.Text = chosen;
            }
        }

        long NeededBytes()
        {
            // The disc is unpacked next to an existing game\ before it replaces
            // it, so an update needs the full size too, for a while.
            return (_disc?.GameBytes ?? 4300000000L) + 2L * 1024 * 1024 * 1024;
        }

        void UpdateSpace()
        {
            string dir = _dirBox.Text.Trim();
            _existingLabel.Text = "";
            try
            {
                if (!Path.IsPathRooted(dir)) throw new ArgumentException();
                var drive = new DriveInfo(Path.GetPathRoot(Path.GetFullPath(dir)));
                _spaceLabel.ForeColor = drive.AvailableFreeSpace >= NeededBytes() ? Muted : Bad;
                _spaceLabel.Text = $"Needs about {InstallJob.Gb(NeededBytes())} \u00B7 {InstallJob.Gb(drive.AvailableFreeSpace)} free on {drive.Name.TrimEnd('\\')}";
                if (InstallJob.IsInstalledIn(dir))
                    _existingLabel.Text = "RE-Amped2 is already installed here. It will be updated; your saves and settings are kept.";
            }
            catch (Exception)
            {
                _spaceLabel.ForeColor = Bad;
                _spaceLabel.Text = "Enter a full folder path, such as C:\\Games\\RE-Amped2.";
            }
            _existingLabel.Visible = _existingLabel.Text.Length > 0;
            UpdateButtons();
        }

        void DetectTools()
        {
            if (_detecting) return;
            _detecting = true;
            _recheck.Visible = false;
            _toolsList.Controls.Clear();
            _toolsList.RowStyles.Clear();
            _toolsList.RowCount = 0;
            AddToolRow("\u2026", Muted, "Checking this PC for the build tools\u2026", null);
            _toolsNote.Text = "";
            UpdateButtons();
            Task.Run(() => Toolchain.Detect(true)).ContinueWith(t =>
            {
                _detecting = false;
                _tools = t.Exception == null ? t.Result : new Toolchain();
                ShowTools();
                UpdateButtons();
            }, TaskScheduler.FromCurrentSynchronizationContext());
        }

        /// <summary>The install-time estimate for this PC, from the tools still missing.</summary>
        int EstimateMinutes() =>
            InstallJob.EstimateMinutes(_tools == null ? Enumerable.Empty<ToolStatus>()
                                                      : _tools.Describe(_menuBox.Checked).Where(t => !t.Found && t.CanInstall));

        string TimeNote(int? minutes) =>
            (minutes == null ? "Installing takes about 10 to 25 minutes, depending on your PC"
                             : $"Installing takes about {minutes} minutes on this PC") +
            "; most of it is compiling. You can keep using your PC meanwhile, though it will be busy.";

        void ShowTools()
        {
            if (_tools == null || _detecting) return;
            _timeNote.Text = TimeNote(EstimateMinutes());
            _toolsList.SuspendLayout();
            _toolsList.Controls.Clear();
            _toolsList.RowStyles.Clear();
            _toolsList.RowCount = 0;
            bool anyInstall = false, anyManual = false;
            foreach (var tool in _tools.Describe(_menuBox.Checked))
            {
                if (tool.Found)
                    AddToolRow("\u2714", Good, $"{tool.Name} \u2014 found{(tool.FoundAs != null && tool.FoundAs != tool.Name ? " (" + tool.FoundAs + ")" : "")}", null);
                else if (tool.CanInstall)
                {
                    anyInstall = true;
                    AddToolRow("\u2B07", Info, $"{tool.Name} \u2014 missing, can be installed for you ({tool.InstallNote.Split(',')[0]})", null);
                }
                else
                {
                    anyManual |= !tool.Optional;
                    AddToolRow("\u2716", tool.Optional ? Muted : Bad,
                               $"{tool.Name} \u2014 missing: {tool.Purpose}. Install it from ", tool.ManualUrl);
                }
            }
            _toolsList.ResumeLayout();
            _recheck.Visible = true;
            _toolsNote.ForeColor = anyManual ? Bad : Muted;
            _toolsNote.Text = anyManual
                ? "Windows can't install these automatically on this PC. Install the missing tools, then click \u201CCheck again\u201D."
                : anyInstall
                    ? "Tools marked \u2B07 are installed only if you agree: Install first shows what each one is, with its licence terms."
                    : "Everything needed is already on this PC. The installer only downloads the recompiler's Python " +
                      "packages, into a temporary folder it removes at the end.";
        }

        void AddToolRow(string mark, Color color, string text, string url)
        {
            int row = _toolsList.RowCount++;
            _toolsList.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            _toolsList.Controls.Add(new Label { Text = mark, ForeColor = color, AutoSize = true, Font = _bold, Margin = new Padding(0, 2, 0, 2) }, 0, row);
            Control body;
            if (url != null)
            {
                var link = new LinkLabel { Text = text + url, AutoSize = true, Anchor = AnchorStyles.Left | AnchorStyles.Right, Margin = new Padding(0, 2, 0, 2), ForeColor = Body };
                link.LinkArea = new LinkArea(text.Length, url.Length);
                link.LinkClicked += (s, e) => Links.Open(url);
                body = link;
            }
            else
                body = new Label { Text = text, AutoSize = true, Anchor = AnchorStyles.Left | AnchorStyles.Right, ForeColor = Body, Margin = new Padding(0, 2, 0, 2) };
            _toolsList.Controls.Add(body, 1, row);
        }

        bool ToolsBlockInstall =>
            _tools == null || _detecting ||
            _tools.Describe(_menuBox.Checked).Any(t => !t.Found && !t.CanInstall && !t.Optional);

        /// <summary>Checks the folder before the install starts; false keeps the player on page 2.</summary>
        bool ValidateLocation()
        {
            string dir = _dirBox.Text.Trim();
            try
            {
                if (!Path.IsPathRooted(dir)) throw new ArgumentException();
                dir = Path.GetFullPath(dir).TrimEnd('\\');
            }
            catch (Exception)
            {
                Warn("Please enter a full folder path, such as C:\\Games\\RE-Amped2.");
                return false;
            }
            if (dir.Length <= 3)
            {
                Warn("Please choose a folder, not the top of a drive (for example " + Path.Combine(dir, "Games\\RE-Amped2") + ").");
                return false;
            }
            foreach (var special in new[] { Environment.SpecialFolder.ProgramFiles, Environment.SpecialFolder.ProgramFilesX86, Environment.SpecialFolder.Windows })
            {
                var sp = Environment.GetFolderPath(special);
                if (sp.Length > 0 && dir.StartsWith(sp, StringComparison.OrdinalIgnoreCase))
                {
                    Warn("The game saves its progress and settings in its own folder, which Windows doesn't allow inside " + sp +
                         ".\n\nPlease choose another folder, such as C:\\Games\\RE-Amped2.");
                    return false;
                }
            }

            bool existing = InstallJob.IsInstalledIn(dir);
            if (!existing && Directory.Exists(dir) && Directory.EnumerateFileSystemEntries(dir).Any() &&
                !File.Exists(Path.Combine(dir, @"game\default.xbe")))
            {
                if (MessageBox.Show(this, $"The folder {dir} isn't empty.\n\nInstall RE-Amped2 into it anyway?", "RE-Amped2 Installer",
                                    MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes)
                    return false;
            }

            try
            {
                Directory.CreateDirectory(dir);
                var probe = Path.Combine(dir, ".write-test");
                File.WriteAllText(probe, "");
                File.Delete(probe);
            }
            catch (Exception)
            {
                Warn("The installer can't write to " + dir + ".\n\nPlease choose a folder you own, such as C:\\Games\\RE-Amped2.");
                return false;
            }

            try
            {
                var free = new DriveInfo(Path.GetPathRoot(dir)).AvailableFreeSpace;
                if (free < NeededBytes())
                {
                    Warn($"There isn't enough free space on {Path.GetPathRoot(dir)}: the install needs about {InstallJob.Gb(NeededBytes())} " +
                         $"and {InstallJob.Gb(free)} is free.");
                    return false;
                }
            }
            catch (Exception) { }

            if (Process.GetProcessesByName(Path.GetFileNameWithoutExtension(InstallJob.ExeName)).Length > 0 ||
                Process.GetProcessesByName(Path.GetFileNameWithoutExtension(InstallJob.LegacyExeName)).Length > 0)
            {
                Warn("RE-Amped2 is running. Close the game first, then click Install again.");
                return false;
            }

            _dirBox.Text = dir;
            return true;
        }

        // ── Page 3 ───────────────────────────────────────────────────

        Panel BuildInstallPage()
        {
            var page = NewPage();
            Add(page, Heading("Installing RE-Amped2"));
            _installIntro = Para("");
            Add(page, _installIntro);

            _stageTable = new TableLayoutPanel { ColumnCount = 2, AutoSize = true, Anchor = AnchorStyles.Left | AnchorStyles.Right, Margin = new Padding(0, 4, 0, 12) };
            _stageTable.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 26));
            _stageTable.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            Add(page, _stageTable);

            _bar = new ProgressBar { Maximum = 1000, Height = 20, Anchor = AnchorStyles.Left | AnchorStyles.Right, Margin = new Padding(0, 2, 0, 6), Style = ProgressBarStyle.Continuous };
            Add(page, _bar);

            var status = new TableLayoutPanel { ColumnCount = 2, AutoSize = true, Anchor = AnchorStyles.Left | AnchorStyles.Right, Margin = new Padding(0) };
            status.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            status.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            _detail = new Label { AutoSize = true, Anchor = AnchorStyles.Left | AnchorStyles.Right, ForeColor = Body, Margin = new Padding(0) };
            _elapsed = new Label { AutoSize = true, ForeColor = Muted, Font = _small, Margin = new Padding(12, 0, 0, 0) };
            status.Controls.Add(_detail, 0, 0);
            status.Controls.Add(_elapsed, 1, 0);
            Add(page, status);

            _detailsToggle = new LinkLabel { Text = "Show details", AutoSize = true, Margin = new Padding(0, 12, 0, 4) };
            _detailsToggle.LinkClicked += (s, e) =>
            {
                _logBox.Visible = !_logBox.Visible;
                _detailsToggle.Text = _logBox.Visible ? "Hide details" : "Show details";
                if (_logBox.Visible) { _logBox.SelectionStart = _logBox.TextLength; _logBox.ScrollToCaret(); }
            };
            Add(page, _detailsToggle);

            _logBox = new TextBox
            {
                Multiline = true,
                ReadOnly = true,
                ScrollBars = ScrollBars.Vertical,
                WordWrap = false,
                Font = _mono,
                BackColor = Color.FromArgb(0xF7, 0xF9, 0xFB),
                Anchor = AnchorStyles.Left | AnchorStyles.Right,
                Height = 150,
                Visible = false,
                Margin = new Padding(0),
            };
            Add(page, _logBox);
            return Wrap(page);
        }

        /// <summary>
        /// Asks before any build tool is installed. True when nothing is
        /// missing or the player agreed; <paramref name="approved"/> then
        /// names the tools the install may fetch.
        /// </summary>
        bool AskToInstallTools(out HashSet<string> approved)
        {
            approved = new HashSet<string>();
            var missing = _tools.Describe(_menuBox.Checked).Where(t => !t.Found && t.CanInstall).ToList();
            if (missing.Count == 0)
                return true;
            if (!ConsentDialog.Ask(this, missing, _menuBox.Checked))
                return false;
            foreach (var t in missing)
                approved.Add(t.Name);
            return true;
        }

        void ShowLicenses()
        {
            try
            {
                var dir = Path.Combine(Payload.Scratch, "licenses");
                if (Payload.ExtractLicenses(dir) > 0)
                    Links.Open(dir);
            }
            catch (Exception e)
            {
                Warn("The licence texts couldn't be shown: " + e.Message);
            }
        }

        void StartInstall(HashSet<string> approvedTools)
        {
            var options = new InstallOptions
            {
                Disc = _disc,
                InstallDir = _dirBox.Text.Trim(),
                DesktopShortcut = _shortcutBox.Checked,
                MenuMod = _menuBox.Checked,
                Look = _lookBox.Checked,
                ApprovedTools = approvedTools,
            };
            _installIntro.Text = "Sit back: the installer is building RE-Amped2 from your disc image, right here on your PC. " +
                                 $"Approx. {EstimateMinutes()} minutes, please be patient; the compiling step is the longest.";
            try
            {
                using (var k = Registry.CurrentUser.CreateSubKey(RegKey))
                    k.SetValue("InstallDir", options.InstallDir);
            }
            catch (Exception) { }

            _stageTable.SuspendLayout();
            _stageTable.Controls.Clear();
            _stageTable.RowStyles.Clear();
            _stageTable.RowCount = 0;
            _stageRows.Clear();
            for (int i = 0; i < InstallJob.StageTitles.Length; i++)
            {
                if (i == 5 && !options.MenuMod) continue;
                int row = _stageTable.RowCount++;
                _stageTable.RowStyles.Add(new RowStyle(SizeType.AutoSize));
                var mark = new Label { Text = "\u25CB", ForeColor = Muted, AutoSize = true, Margin = new Padding(0, 3, 0, 3) };
                var title = new Label { Text = InstallJob.StageTitles[i], ForeColor = Muted, AutoSize = true, Margin = new Padding(0, 3, 0, 3) };
                _stageTable.Controls.Add(mark, 0, row);
                _stageTable.Controls.Add(title, 1, row);
                _stageRows.Add((mark, title, i));
            }
            _stageTable.ResumeLayout();

            _logBox.Clear();
            _bar.Value = 0;
            _detail.Text = "Starting\u2026";
            _elapsed.Text = "";
            _job = new InstallJob(options);
            _jobThread = new Thread(_job.Run) { IsBackground = true, Name = "install" };
            _clock.Restart();
            _jobThread.Start();
            _timer.Start();
        }

        void PollJob()
        {
            if (_job == null) return;
            int stage = _job.Stage;
            foreach (var (mark, title, i) in _stageRows)
            {
                if (i < stage) { mark.Text = "\u2714"; mark.ForeColor = Good; title.ForeColor = Body; title.Font = _base; }
                else if (i == stage) { mark.Text = "\u25B6"; mark.ForeColor = Accent; title.ForeColor = Ink; title.Font = _bold; }
            }
            _bar.Value = Math.Max(0, Math.Min(1000, (int)(_job.Percent * 10)));
            if (_job.Result == null && !_cancelRequested)
                _detail.Text = _job.Detail;
            var t = _clock.Elapsed;
            _elapsed.Text = $"{(int)t.TotalMinutes}:{t.Seconds:00} elapsed";

            if (_job.LogLines.Count > 0)
            {
                var sb = new System.Text.StringBuilder();
                while (_job.LogLines.TryDequeue(out var line))
                    sb.Append(line).Append("\r\n");
                // Keep the box to the last ~4000 lines' worth.
                if (_logBox.TextLength > 400000)
                    _logBox.Text = _logBox.Text.Substring(_logBox.TextLength - 200000);
                _logBox.AppendText(sb.ToString());
            }

            if (_job.Result != null)
            {
                _timer.Stop();
                _clock.Stop();
                var result = _job.Result;
                if (_closeWhenStopped) { Close(); return; }
                ShowResult(result);
            }
        }

        bool _cancelRequested;

        void CancelClicked()
        {
            if (_page == 2 && _job != null && _job.Result == null)
            {
                if (MessageBox.Show(this, "Stop the installation?\n\nYou can run the installer again later.", "RE-Amped2 Installer",
                                    MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes)
                    return;
                _cancelRequested = true;
                _cancel.Enabled = false;
                _detail.Text = "Stopping\u2026";
                _job.Cancel();
                return;
            }
            Close();
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            if (_job != null && _job.Result == null)
            {
                e.Cancel = true;
                if (_cancelRequested) return;
                if (MessageBox.Show(this, "Stop the installation and close the installer?", "RE-Amped2 Installer",
                                    MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes)
                {
                    _cancelRequested = true;
                    _closeWhenStopped = true;
                    _cancel.Enabled = false;
                    _detail.Text = "Stopping\u2026";
                    _job.Cancel();
                }
                return;
            }
            base.OnFormClosing(e);
        }

        // ── Page 4 ───────────────────────────────────────────────────

        Panel BuildDonePage()
        {
            _donePage = NewPage();
            return Wrap(_donePage);
        }

        void ShowResult(InstallResult r)
        {
            var page = _donePage;
            page.SuspendLayout();
            page.Controls.Clear();
            page.RowStyles.Clear();
            page.RowCount = 0;
            _launchBox = null;

            if (r.Success)
            {
                var title = new TableLayoutPanel { ColumnCount = 2, AutoSize = true, Margin = new Padding(0, 0, 0, 6) };
                if (_badge != null)
                    title.Controls.Add(new PictureBox
                    {
                        Image = _badge,
                        SizeMode = PictureBoxSizeMode.Zoom,
                        Size = new Size(56, 56),
                        Margin = new Padding(0, 0, 12, 0),
                    }, 0, 0);
                var heading = Heading("RE-Amped2 is ready to ride");
                heading.Anchor = AnchorStyles.Left;
                heading.Margin = new Padding(0);
                title.Controls.Add(heading, 1, 0);
                Add(page, title);
                var summary = new LinkLabel { AutoSize = true, Anchor = AnchorStyles.Left | AnchorStyles.Right, ForeColor = Body, Margin = new Padding(0, 0, 0, 12) };
                string head = $"Built from your Amped 2 ({_disc.RegionName}) disc in {Minutes(r.Duration)} and {(r.WasUpdate ? "updated in" : "installed to")} ";
                summary.Text = head + r.InstallDir + ".";
                summary.LinkArea = new LinkArea(head.Length, r.InstallDir.Length);
                summary.LinkClicked += (s, e) => Links.Open(r.InstallDir);
                Add(page, summary);

                Add(page, Label("Good to know", _bold, Ink, new Padding(0, 0, 0, 4)));
                var tips = new List<string>
                {
                    r.ShortcutCreated
                        ? "Start the game with the RE-Amped2 shortcut on your desktop."
                        : $"Start the game with {InstallJob.ExeName} in the install folder.",
                    "Play with an Xbox-style controller or the keyboard: arrow keys steer, Z X A S are the A B X Y buttons, Enter is Start.",
                    "F11 or Alt+Enter switches between a window and full screen.",
                    r.MenuModInstalled
                        ? "Options and Mods \u203A Game Options has Window and Resolution settings, and the main menu has Quit Game."
                        : "More settings (window size, resolution, controls) are in amped2.ini in the install folder, created when the game first starts.",
                    "This is an early-access build: expect bugs. If something goes wrong, the install folder's amped2.log helps us find out why.",
                    "Your career progress is saved in the game\\UDATA folder inside the install folder. Running this installer again keeps it.",
                    "README.txt in the install folder has all of this to look up later.",
                };
                if (r.MenuModNote != null)
                    tips.Add(r.MenuModNote + " The game plays fine without them.");
                tips.AddRange(r.Warnings);
                foreach (var tip in tips)
                    Add(page, Bullet(tip));

                Add(page, FeedbackBox("Tell us how it rides",
                    "Bugs, crashes, anything that looks off: report them on GitHub, with amped2.log from the install folder. " +
                    "New versions appear on the same page."));

                _launchBox = new CheckBox { Text = "Start RE-Amped2 now", Checked = true, AutoSize = true, Margin = new Padding(0, 10, 0, 0) };
                Add(page, _launchBox);
            }
            else if (r.Cancelled)
            {
                Add(page, Heading("Installation cancelled"));
                Add(page, Para(r.WasUpdate
                    ? "The installation was stopped before it finished. Your existing RE-Amped2 and its saves are still there; " +
                      "run the installer again whenever you like to update it."
                    : "The installation was stopped before it finished, so RE-Amped2 isn't ready to play yet. " +
                      $"Run the installer again to finish, or delete {r.InstallDir} if you've changed your mind."));
                AddLogLink(page, r);
            }
            else
            {
                Add(page, Heading("The installation didn't finish"));
                if (r.FailedStage != null)
                    Add(page, Para("Something went wrong at this step: " + r.FailedStage.ToLowerInvariant() + "."));
                var error = Para(r.Error ?? "Unknown error.", Bad);
                error.Font = _bold;
                Add(page, error);
                if (!string.IsNullOrEmpty(r.Advice))
                    Add(page, Para(r.Advice));
                AddLogLink(page, r);
                Add(page, FeedbackBox("Need a hand?",
                    "Report it on GitHub, with the install log and the step that went wrong."));
            }
            AddFill(page);   // leftover height below the content, not between rows
            page.ResumeLayout();
            ShowPage(3);
            _next.Text = r.Success ? "Finish" : "Close";
            _back.Visible = !r.Success;
            _back.Text = "Try again";
            _cancel.Visible = false;
        }

        void AddLogLink(TableLayoutPanel page, InstallResult r)
        {
            if (r.LogPath == null || !File.Exists(r.LogPath)) return;
            const string lead = "Install log: ";
            var link = new LinkLabel { Text = lead + r.LogPath, AutoSize = true, Anchor = AnchorStyles.Left | AnchorStyles.Right, Margin = new Padding(0, 4, 0, 8) };
            link.LinkArea = new LinkArea(lead.Length, r.LogPath.Length);
            link.LinkClicked += (s, e) => Links.Open(r.LogPath);
            Add(page, link);
        }

        Control FeedbackBox(string title, string text)
        {
            var box = new TableLayoutPanel
            {
                ColumnCount = 2,
                AutoSize = true,
                Anchor = AnchorStyles.Left | AnchorStyles.Right,
                BackColor = FeedbackBg,
                Padding = new Padding(14, 12, 14, 12),
                Margin = new Padding(0, 14, 0, 0),
            };
            box.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            box.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            box.Paint += (s, e) => { using (var p = new Pen(FeedbackBorder)) e.Graphics.DrawRectangle(p, 0, 0, box.Width - 1, box.Height - 1); };
            var words = new TableLayoutPanel { ColumnCount = 1, AutoSize = true, Anchor = AnchorStyles.Left | AnchorStyles.Right, Margin = new Padding(0), BackColor = FeedbackBg };
            words.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            words.Controls.Add(Label(title, _bold, Ink, new Padding(0, 0, 0, 4)), 0, 0);
            words.Controls.Add(Label(text, _base, Body, new Padding(0)), 0, 1);
            var button = MakeButton("Report a problem", true);
            button.Anchor = AnchorStyles.Right;
            button.Margin = new Padding(14, 0, 0, 0);
            button.Click += (s, e) => Links.Open(Links.Issues);
            var tip = new ToolTip();
            tip.SetToolTip(button, Links.Issues);
            box.Controls.Add(words, 0, 0);
            box.Controls.Add(button, 1, 0);
            return box;
        }

        static string Minutes(TimeSpan t)
        {
            int m = (int)Math.Round(t.TotalMinutes);
            return m <= 1 ? "about a minute" : $"{m} minutes";
        }

        // ── Navigation ───────────────────────────────────────────────

        void ShowPage(int i)
        {
            _page = i;
            for (int p = 0; p < _pages.Length; p++)
                _pages[p].Visible = p == i;
            for (int s = 0; s < 4; s++)
            {
                _stepLabels[s].ForeColor = s == i ? Color.White : s < i ? Color.FromArgb(0x7F, 0xD1, 0xA8) : Color.FromArgb(0x8A, 0xA4, 0xC0);
                _stepLabels[s].Font = s == i ? _bold : _base;
                _stepLabels[s].Invalidate();
            }
            _back.Visible = i == 1;
            _back.Text = "Back";
            _cancel.Visible = i < 3;
            _cancel.Enabled = true;
            _next.Visible = i != 2;
            _next.Text = i == 1 ? "Install" : i == 3 ? "Finish" : "Next";
            if (i == 1)
            {
                UpdateSpace();
                if (_tools == null) DetectTools();
            }
            UpdateButtons();
        }

        void UpdateButtons()
        {
            if (_page == 0)
                _next.Enabled = _disc != null && !_checkingIso;
            else if (_page == 1)
                _next.Enabled = !ToolsBlockInstall && _spaceLabel.ForeColor != Bad;
            else
                _next.Enabled = true;
        }

        void GoNext()
        {
            switch (_page)
            {
                case 0:
                    ShowPage(1);
                    break;
                case 1:
                    if (!ValidateLocation()) return;
                    if (!AskToInstallTools(out var approved)) return;
                    _cancelRequested = false;
                    ShowPage(2);
                    StartInstall(approved);
                    break;
                case 3:
                    if (_launchBox != null && _launchBox.Checked && _job?.Result?.ExePath != null)
                    {
                        try
                        {
                            Process.Start(new ProcessStartInfo(_job.Result.ExePath)
                            { WorkingDirectory = _job.Result.InstallDir, UseShellExecute = true });
                        }
                        catch (Exception) { }
                    }
                    _job = null;
                    Close();
                    break;
            }
        }

        void GoBack()
        {
            if (_page == 1)
                ShowPage(0);
            else if (_page == 3)
            {
                _job = null;      // "Try again"
                _tools = null;    // they may have installed something meanwhile
                ShowPage(1);
            }
        }

        // ── Building blocks ──────────────────────────────────────────

        TableLayoutPanel NewPage()
        {
            var t = new TableLayoutPanel
            {
                Dock = DockStyle.Fill,
                ColumnCount = 1,
                Padding = new Padding(34, 24, 34, 12),
                BackColor = Color.White,
            };
            t.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            return t;
        }

        static Panel Wrap(TableLayoutPanel page)
        {
            var p = new Panel { Dock = DockStyle.Fill, BackColor = Color.White };
            p.Controls.Add(page);
            return p;
        }

        static void Add(TableLayoutPanel t, Control c)
        {
            int row = t.RowCount++;
            t.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            t.Controls.Add(c, 0, row);
        }

        /// <summary>An empty row that takes the leftover height, pushing what follows to the bottom.</summary>
        static void AddFill(TableLayoutPanel t)
        {
            int row = t.RowCount++;
            t.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            t.Controls.Add(new Panel { Dock = DockStyle.Fill, Margin = new Padding(0), Height = 1 }, 0, row);
        }

        Label Heading(string text) => Label(text, _h1, Ink, new Padding(0, 0, 0, 10));

        Label Para(string text, Color? color = null, Font font = null) =>
            Label(text, font ?? _base, color ?? Body, new Padding(0, 0, 0, 10));

        static Label Label(string text, Font font, Color color, Padding margin) => new Label
        {
            Text = text,
            Font = font,
            ForeColor = color,
            AutoSize = true,
            Anchor = AnchorStyles.Left | AnchorStyles.Right,
            Margin = margin,
        };

        Control Bullet(string text)
        {
            var t = new TableLayoutPanel { ColumnCount = 2, AutoSize = true, Anchor = AnchorStyles.Left | AnchorStyles.Right, Margin = new Padding(0, 0, 0, 4) };
            t.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 20));
            t.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            t.Controls.Add(new Label { Text = "\u2022", ForeColor = Accent, AutoSize = true, Font = _bold, Margin = new Padding(2, 0, 0, 0) }, 0, 0);
            t.Controls.Add(Label(text, _base, Body, new Padding(0)), 1, 0);
            return t;
        }

        Control Row(out TextBox box, string buttonText, Action onClick)
        {
            var t = new TableLayoutPanel { ColumnCount = 2, AutoSize = true, Anchor = AnchorStyles.Left | AnchorStyles.Right, Margin = new Padding(0, 6, 0, 0) };
            t.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            t.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            box = new TextBox { Anchor = AnchorStyles.Left | AnchorStyles.Right, Margin = new Padding(0, 1, 8, 0) };
            var b = MakeButton(buttonText, false);
            b.Margin = new Padding(0);
            b.Click += (s, e) => onClick();
            t.Controls.Add(box, 0, 0);
            t.Controls.Add(b, 1, 0);
            return t;
        }

        Button MakeButton(string text, bool primary)
        {
            var b = new Button
            {
                Text = text,
                AutoSize = true,
                MinimumSize = new Size(96, 30),
                Padding = new Padding(8, 0, 8, 0),
                Margin = new Padding(8, 0, 0, 0),
                UseVisualStyleBackColor = !primary,
            };
            if (primary)
            {
                b.FlatStyle = FlatStyle.Flat;
                b.FlatAppearance.BorderSize = 0;
                b.BackColor = Accent;
                b.ForeColor = Color.White;
                b.Font = _bold;
                b.Cursor = Cursors.Hand;
                var normal = Accent;
                b.BackColorChanged += (s, e) => { if (b.Enabled) normal = b.BackColor; };
                b.EnabledChanged += (s, e) => b.BackColor = b.Enabled ? normal : Color.FromArgb(0xB8, 0xC4, 0xCF);
            }
            return b;
        }

        void Warn(string text) => MessageBox.Show(this, text, "RE-Amped2 Installer", MessageBoxButtons.OK, MessageBoxIcon.Warning);

        void PaintHeader(object sender, PaintEventArgs e)
        {
            var g = e.Graphics;
            var r = _header.ClientRectangle;
            using (var bg = new LinearGradientBrush(r, Navy, NavyLight, LinearGradientMode.Horizontal))
                g.FillRectangle(bg, r);
            if (_headerArt != null)
            {
                // tools/branding/build.py makes it 1600x280, for 800x140 at 200%: scale to cover.
                float s = Math.Max(r.Width / (float)_headerArt.Width, r.Height / (float)_headerArt.Height);
                g.InterpolationMode = InterpolationMode.HighQualityBicubic;
                g.PixelOffsetMode = PixelOffsetMode.HighQuality;
                g.DrawImage(_headerArt, 0, 0, _headerArt.Width * s, _headerArt.Height * s);
            }
            using (var p = new Pen(Glow, 2)) g.DrawLine(p, 0, r.Height - 1, r.Width, r.Height - 1);

            // Under the logo: an EARLY ACCESS tag and the subtitle.
            g.SmoothingMode = SmoothingMode.AntiAlias;
            g.TextRenderingHint = System.Drawing.Text.TextRenderingHint.ClearTypeGridFit;
            float scale = r.Height / 140f, x = 22 * scale, y = 94 * scale;
            using (var tagFont = new Font("Segoe UI", 7.5f, FontStyle.Bold))
            {
                const string tag = "EARLY ACCESS";
                var size = g.MeasureString(tag, tagFont);
                var box = new RectangleF(x, y, size.Width + 8 * scale, size.Height + 2 * scale);
                using (var path = Rounded(box, 4 * scale))
                using (var b = new SolidBrush(Glow))
                    g.FillPath(b, path);
                using (var b = new SolidBrush(Navy))
                    g.DrawString(tag, tagFont, b, x + 4 * scale, y + 1 * scale);
                using (var b = new SolidBrush(HeaderSub))
                    g.DrawString("Builds the game from your own disc", _small, b, x - 1 * scale, box.Bottom + 3 * scale);
            }
        }

        static GraphicsPath Rounded(RectangleF r, float radius)
        {
            var p = new GraphicsPath();
            float d = radius * 2;
            p.AddArc(r.X, r.Y, d, d, 180, 90);
            p.AddArc(r.Right - d, r.Y, d, d, 270, 90);
            p.AddArc(r.Right - d, r.Bottom - d, d, d, 0, 90);
            p.AddArc(r.X, r.Bottom - d, d, d, 90, 90);
            p.CloseFigure();
            return p;
        }

        static Image LoadImage(string name)
        {
            try
            {
                using (var s = typeof(WizardForm).Assembly.GetManifestResourceStream(name))
                    return s == null ? null : new Bitmap(Image.FromStream(s));
            }
            catch (Exception) { return null; }
        }

        void PaintStepUnderline(object sender, PaintEventArgs e)
        {
            var label = (Label)sender;
            int i = Array.IndexOf(_stepLabels, label);
            if (i != _page) return;
            using (var b = new SolidBrush(Glow))
                e.Graphics.FillRectangle(b, 0, label.Height - 3, label.Width, 3);
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _timer.Dispose();
                foreach (var f in new[] { _base, _bold, _h1, _small, _mono }) f.Dispose();
                _headerArt?.Dispose();
                _badge?.Dispose();
            }
            base.Dispose(disposing);
        }

        sealed class DoubleBufferedPanel : Panel
        {
            public DoubleBufferedPanel()
            {
                DoubleBuffered = true;
                ResizeRedraw = true;
            }
        }
    }
}
