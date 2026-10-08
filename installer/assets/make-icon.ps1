<#
.SYNOPSIS
    Draws amped2.ico (installer, window and desktop-shortcut icon).

    A rounded square in night blue with a snowy peak and an italic "2".
    Every size is drawn on its own rather than scaled, and stored as PNG
    inside the .ico (fine on Windows Vista and later).
#>
Add-Type -AssemblyName System.Drawing

$sizes = 16, 24, 32, 48, 64, 128, 256
$out = Join-Path $PSScriptRoot 'amped2.ico'

function Draw([int]$n) {
    $bmp = New-Object System.Drawing.Bitmap $n, $n
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = 'AntiAlias'
    $g.TextRenderingHint = 'AntiAliasGridFit'
    $g.Clear([System.Drawing.Color]::Transparent)

    $r = [single]($n * 0.2)
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $w = [single]($n - 1)
    $path.AddArc(0, 0, $r, $r, 180, 90)
    $path.AddArc($w - $r, 0, $r, $r, 270, 90)
    $path.AddArc($w - $r, $w - $r, $r, $r, 0, 90)
    $path.AddArc(0, $w - $r, $r, $r, 90, 90)
    $path.CloseFigure()
    $rect = New-Object System.Drawing.RectangleF 0, 0, $n, $n
    $bg = New-Object System.Drawing.Drawing2D.LinearGradientBrush $rect,
        ([System.Drawing.Color]::FromArgb(0x0F, 0x1E, 0x2E)),
        ([System.Drawing.Color]::FromArgb(0x1E, 0x7F, 0xD8)), 60
    $g.FillPath($bg, $path)
    $g.SetClip($path)

    # The "2", upper part.
    $fontSize = [single]($n * 0.62)
    $font = New-Object System.Drawing.Font 'Segoe UI Black', $fontSize, ([System.Drawing.FontStyle]::Italic), ([System.Drawing.GraphicsUnit]::Pixel)
    $fmt = New-Object System.Drawing.StringFormat
    $fmt.Alignment = 'Center'
    $fmt.LineAlignment = 'Center'
    $textRect = New-Object System.Drawing.RectangleF ([single]($n * 0.04)), ([single](-$n * 0.10)), $n, ([single]($n * 0.9))
    $g.DrawString('2', $font, [System.Drawing.Brushes]::White, $textRect, $fmt)

    # Snowy peaks along the bottom.
    $far = @(
        (New-Object System.Drawing.PointF 0, $n),
        (New-Object System.Drawing.PointF ([single]($n * 0.30)), ([single]($n * 0.66))),
        (New-Object System.Drawing.PointF ([single]($n * 0.48)), ([single]($n * 0.80))),
        (New-Object System.Drawing.PointF ([single]($n * 0.74)), ([single]($n * 0.58))),
        (New-Object System.Drawing.PointF $n, ([single]($n * 0.78))),
        (New-Object System.Drawing.PointF $n, $n))
    $near = @(
        (New-Object System.Drawing.PointF 0, ([single]($n * 0.92))),
        (New-Object System.Drawing.PointF ([single]($n * 0.42)), ([single]($n * 0.76))),
        (New-Object System.Drawing.PointF $n, ([single]($n * 0.94))),
        (New-Object System.Drawing.PointF $n, $n),
        (New-Object System.Drawing.PointF 0, $n))
    $snow1 = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(150, 255, 255, 255))
    $snow2 = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 255, 255, 255))
    $g.FillPolygon($snow1, $far)
    $g.FillPolygon($snow2, $near)

    $g.Dispose()
    $ms = New-Object System.IO.MemoryStream
    if ($n -ge 256) {
        $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    } else {
        # Classic 32-bit DIB entry: header (double height for the mask),
        # BGRA rows bottom-up, then an all-zero AND mask (alpha decides).
        $bw = New-Object System.IO.BinaryWriter $ms
        $bw.Write([uint32]40); $bw.Write([int32]$n); $bw.Write([int32]($n * 2))
        $bw.Write([uint16]1); $bw.Write([uint16]32); $bw.Write([uint32]0)
        $bw.Write([uint32]($n * $n * 4)); $bw.Write([int32]0); $bw.Write([int32]0)
        $bw.Write([uint32]0); $bw.Write([uint32]0)
        for ($y = $n - 1; $y -ge 0; $y--) {
            for ($x = 0; $x -lt $n; $x++) {
                $c = $bmp.GetPixel($x, $y)
                $bw.Write([byte]$c.B); $bw.Write([byte]$c.G); $bw.Write([byte]$c.R); $bw.Write([byte]$c.A)
            }
        }
        $maskRow = [int]([math]::Ceiling($n / 32.0) * 4)
        $bw.Write((New-Object byte[] ($maskRow * $n)))
        $bw.Flush()
    }
    $bmp.Dispose()
    return , $ms.ToArray()
}

$images = foreach ($n in $sizes) { , (Draw $n) }

$fs = [System.IO.File]::Create($out)
$bw = New-Object System.IO.BinaryWriter $fs
$bw.Write([uint16]0); $bw.Write([uint16]1); $bw.Write([uint16]$sizes.Count)
$offset = 6 + 16 * $sizes.Count
for ($i = 0; $i -lt $sizes.Count; $i++) {
    $n = $sizes[$i]
    $dim = if ($n -ge 256) { 0 } else { $n }
    $bw.Write([byte]$dim); $bw.Write([byte]$dim); $bw.Write([byte]0); $bw.Write([byte]0)
    $bw.Write([uint16]1); $bw.Write([uint16]32)
    $bw.Write([uint32]$images[$i].Length); $bw.Write([uint32]$offset)
    $offset += $images[$i].Length
}
foreach ($img in $images) { $bw.Write($img) }
$bw.Dispose()
Write-Host "Wrote $out"
