using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;

namespace Amped2Installer
{
    sealed class DiscInfo
    {
        public string IsoPath;
        public uint TitleId;
        public string Title;
        public uint Region;
        public long GameBytes;      // sum of the files on the disc
        public int FileCount;
        public Dictionary<string, long> FileSizes = new Dictionary<string, long>(StringComparer.OrdinalIgnoreCase);

        public bool IsAmped2 => TitleId == DiscImage.Amped2TitleId;

        public string RegionName
        {
            get
            {
                if (Region == 1) return "USA";
                if (Region == 4) return "Europe";
                if (Region == 2) return "Japan";
                if ((Region & 0x7) == 0x7) return "region free";
                return "region 0x" + Region.ToString("X");
            }
        }
    }

    /// <summary>Reads a disc image with xdvdfs and checks it is Amped 2.</summary>
    static class DiscImage
    {
        public const uint Amped2TitleId = 0x4D530041;   // "MS-065", both releases

        /// <summary>Throws with a player-facing message when the image is unusable.</summary>
        public static DiscInfo Inspect(string isoPath)
        {
            var info = new DiscInfo { IsoPath = isoPath };
            var xdvdfs = Payload.Xdvdfs;

            // Listing first: it fails fast on anything that is not an Xbox image.
            var tree = ProcessRunner.Capture(xdvdfs, "tree " + ProcessRunner.Quote(isoPath), out int code, 120000);
            if (tree == null || code != 0)
                throw new UserFacingException(
                    "This file can't be read as an Xbox disc image.",
                    "Make sure it is a full .iso or .xiso image of the game disc, not a zip or a single file from it.");

            var line = new Regex(@"^(/.+?) \((\d+) bytes\)\s*$");
            foreach (var raw in tree.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
            {
                var m = line.Match(raw);
                if (!m.Success || m.Groups[1].Value.EndsWith("/"))
                    continue;
                long size = long.Parse(m.Groups[2].Value);
                info.FileSizes[m.Groups[1].Value.TrimStart('/').Replace('/', '\\')] = size;
                info.GameBytes += size;
                info.FileCount++;
            }
            if (!info.FileSizes.ContainsKey("default.xbe"))
                throw new UserFacingException(
                    "This disc image has no game program (default.xbe) on it.",
                    "It may be a DVD video or a damaged image. Make a fresh image of your Amped 2 disc.");

            var xbe = Path.Combine(Payload.Scratch, "default.xbe");
            if (File.Exists(xbe))
                File.Delete(xbe);
            ProcessRunner.Capture(xdvdfs, $"copy-out {ProcessRunner.Quote(isoPath)} default.xbe {ProcessRunner.Quote(xbe)}", out code, 120000);
            if (code != 0 || !File.Exists(xbe))
                throw new UserFacingException("The game program on this disc image couldn't be read.",
                                              "The image may be damaged. Make a fresh image of your disc.");
            ParseXbe(File.ReadAllBytes(xbe), info);

            if (!info.IsAmped2)
                throw new UserFacingException(
                    string.IsNullOrWhiteSpace(info.Title)
                        ? "This is a disc image of a different game, not Amped 2."
                        : $"This is a disc image of “{info.Title}”, not Amped 2.",
                    "Choose an image of Amped 2 (USA or Europe).");
            return info;
        }

        /// <summary>Title ID, name and region from the XBE certificate.</summary>
        static void ParseXbe(byte[] x, DiscInfo info)
        {
            if (x.Length < 0x200 || Encoding.ASCII.GetString(x, 0, 4) != "XBEH")
                throw new UserFacingException("The game program on this disc image isn't valid.",
                                              "The image may be damaged. Make a fresh image of your disc.");
            uint baseAddr = BitConverter.ToUInt32(x, 0x104);
            uint certAddr = BitConverter.ToUInt32(x, 0x118);
            long cert = (long)certAddr - baseAddr;
            if (cert < 0 || cert + 0xA4 > x.Length)
                throw new UserFacingException("The game program on this disc image isn't valid.",
                                              "The image may be damaged. Make a fresh image of your disc.");
            info.TitleId = BitConverter.ToUInt32(x, (int)cert + 0x08);
            info.Title = Encoding.Unicode.GetString(x, (int)cert + 0x0C, 80).TrimEnd('\0').Trim();
            info.Region = BitConverter.ToUInt32(x, (int)cert + 0xA0);
        }
    }

    /// <summary>An error with a short headline and advice a player can act on.</summary>
    sealed class UserFacingException : Exception
    {
        public string Advice { get; }

        public UserFacingException(string message, string advice, Exception inner = null)
            : base(message, inner)
        {
            Advice = advice;
        }
    }
}
