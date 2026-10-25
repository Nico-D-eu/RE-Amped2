using System;
using System.Collections.Generic;
using System.Drawing;
using System.Linq;
using System.Windows.Forms;

namespace Amped2Installer
{
    /// <summary>
    /// Asked when Install is clicked and some build tools are missing: lists
    /// each tool the installer would fetch with winget (publisher, size,
    /// licence terms) and installs nothing unless the player ticks the box
    /// and clicks "Agree and install". winget is only told to accept the
    /// package agreements after that.
    /// </summary>
    sealed class ConsentDialog : Form
    {
        static readonly Color Ink = Color.FromArgb(0x1B, 0x27, 0x33);
        static readonly Color Body = Color.FromArgb(0x3C, 0x4A, 0x57);
        static readonly Color Muted = Color.FromArgb(0x6B, 0x7A, 0x88);
        static readonly Color Accent = Color.FromArgb(0x16, 0x7E, 0xE6);
        static readonly Color FooterBg = Color.FromArgb(0xF4, 0xF6, 0xF8);

        readonly Font _base = new Font("Segoe UI", 9.75f);
        readonly Font _bold = new Font("Segoe UI Semibold", 9.75f);
        readonly Font _h1 = new Font("Segoe UI Semibold", 13f);
        readonly Font _small = new Font("Segoe UI", 8.75f);

        /// <summary>Shows the dialog; true only when the player agreed.</summary>
        public static bool Ask(IWin32Window owner, IList<ToolStatus> tools, bool menuPackages)
        {
            using (var d = new ConsentDialog(tools, menuPackages))
                return d.ShowDialog(owner) == DialogResult.OK;
        }

        ConsentDialog(IList<ToolStatus> tools, bool menuPackages)
        {
            SuspendLayout();
            Text = "RE-Amped2 Installer";
            Font = _base;
            BackColor = Color.White;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = MinimizeBox = false;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.CenterParent;

            var page = new TableLayoutPanel
            {
                ColumnCount = 1,
                AutoSize = true,
                Location = new Point(0, 0),
                Padding = new Padding(24, 18, 24, 8),
                MaximumSize = new Size(620, 0),
                MinimumSize = new Size(620, 0),
            };
            page.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            void Add(Control c) { page.RowCount++; page.RowStyles.Add(new RowStyle(SizeType.AutoSize)); page.Controls.Add(c, 0, page.RowCount - 1); }

            Add(Line(tools.Count == 1 ? "Install this free tool?" : $"Install these {tools.Count} free tools?", _h1, Ink, 8));
            Add(Line("Building RE-Amped2 needs " + (tools.Count == 1 ? "a tool" : "some tools") +
                     " this PC doesn't have yet. With your permission, the installer downloads " +
                     (tools.Count == 1 ? "it" : "them") + " from the publisher with Windows' package manager (winget) " +
                     "and installs " + (tools.Count == 1 ? "it" : "them") + " like any other program.", _base, Body, 12));

            foreach (var t in tools)
            {
                Add(Line(t.Name, _bold, Ink, 0));
                Add(Line($"{t.Publisher} · {Capital(t.Purpose)} · {t.InstallNote}", _small, Body, 0));
                const string lead = "Licence terms: ";
                var link = new LinkLabel
                {
                    Text = lead + t.LicenseUrl,
                    AutoSize = true,
                    Font = _small,
                    LinkArea = new LinkArea(lead.Length, t.LicenseUrl.Length),
                    ForeColor = Body,
                    Margin = new Padding(0, 0, 0, 10),
                };
                var url = t.LicenseUrl;
                link.LinkClicked += (s, e) => Links.Open(url);
                Add(link);
            }

            Add(Line("They stay on your PC after RE-Amped2 is installed, and can be removed later in Settings › Apps " +
                     "like any other program. Windows may ask for administrator rights while they install.", _small, Muted, 6));
            Add(Line("The installer also downloads the recompiler's Python packages (Capstone" +
                     (menuPackages ? "; NumPy and Pillow for the RE-Amped2 menus" : "") +
                     ") from PyPI into a temporary folder, which is removed when the install finishes.", _small, Muted, 12));

            var agree = new CheckBox
            {
                Text = tools.Count == 1
                    ? "I accept this tool's licence terms and want it installed"
                    : "I accept these tools' licence terms and want them installed",
                AutoSize = true,
                Margin = new Padding(0, 0, 0, 8),
            };
            Add(agree);

            var footer = new FlowLayoutPanel
            {
                FlowDirection = FlowDirection.RightToLeft,
                AutoSize = true,
                BackColor = FooterBg,
                Padding = new Padding(0, 10, 16, 10),
                MinimumSize = new Size(620, 0),
                MaximumSize = new Size(620, 0),
            };
            var cancel = new Button { Text = "Don't install", AutoSize = true, MinimumSize = new Size(96, 30), DialogResult = DialogResult.Cancel, Margin = new Padding(8, 0, 0, 0) };
            var ok = new Button
            {
                Text = "Agree and install",
                AutoSize = true,
                MinimumSize = new Size(96, 30),
                Padding = new Padding(8, 0, 8, 0),
                DialogResult = DialogResult.OK,
                Enabled = false,
                FlatStyle = FlatStyle.Flat,
                BackColor = Color.FromArgb(0xB8, 0xC4, 0xCF),
                ForeColor = Color.White,
                Font = _bold,
                Margin = new Padding(8, 0, 0, 0),
            };
            ok.FlatAppearance.BorderSize = 0;
            agree.CheckedChanged += (s, e) =>
            {
                ok.Enabled = agree.Checked;
                ok.BackColor = agree.Checked ? Accent : Color.FromArgb(0xB8, 0xC4, 0xCF);
            };
            footer.Controls.Add(cancel);
            footer.Controls.Add(ok);

            Controls.Add(footer);
            Controls.Add(page);
            AcceptButton = null;   // Enter must not agree on the player's behalf
            CancelButton = cancel;

            AutoScaleDimensions = new SizeF(96f, 96f);
            AutoScaleMode = AutoScaleMode.Dpi;
            ResumeLayout(false);
            PerformLayout();
            // The page and the footer size themselves; the window wraps them.
            footer.Location = new Point(0, page.Bottom);
            ClientSize = new Size(page.Width, footer.Bottom);
        }

        static string Capital(string s) => string.IsNullOrEmpty(s) ? s : char.ToUpperInvariant(s[0]) + s.Substring(1);

        static Label Line(string text, Font font, Color color, int bottom) => new Label
        {
            Text = text,
            Font = font,
            ForeColor = color,
            AutoSize = true,
            MaximumSize = new Size(572, 0),
            Margin = new Padding(0, 0, 0, bottom),
        };

        protected override void Dispose(bool disposing)
        {
            if (disposing)
                foreach (var f in new[] { _base, _bold, _h1, _small }) f.Dispose();
            base.Dispose(disposing);
        }
    }
}
