using Microsoft.UI.Xaml.Media;
using Windows.UI;

namespace Laiaudio;

/// <summary>Paolium dark palette (docs/design.md).</summary>
static class Palette
{
    public static readonly Color Depth = Rgb(0x000000), Base = Rgb(0x141414), Surface = Rgb(0x2C2C2E),
        Border = Rgb(0x3A3A3C), Text = Rgb(0xD6DAE0), Muted = Rgb(0xD6DAE0, 0x99), Sapphire = Rgb(0x0D71FD),
        SapphireText = Rgb(0x5C9DFE), SapphireLight = Rgb(0x93BEFE), Ruby = Rgb(0xFA4F67), RubyLight = Rgb(0xFC8798),
        Gold = Rgb(0xD69D00), Carbon = Rgb(0x95D700);

    public static Color Rgb(uint rgb, byte alpha = 0xFF) =>
        Color.FromArgb(alpha, (byte)(rgb >> 16), (byte)(rgb >> 8), (byte)rgb);

    public static SolidColorBrush Brush(Color color) => new(color);

    public static SolidColorBrush Brush(Color color, double opacity) => new(color) { Opacity = opacity };
}
