using System.Text;
using System.Text.Json.Nodes;
using Microsoft.UI;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.Graphics;

namespace Laiaudio;

/// <summary>Floating captions: a topmost window, out of the taskbar and Alt+Tab, that never takes the focus.
/// Clicks pass through it except over the drag handle; a press there lets Windows move it. Fixed monospaced lines
/// that never jump or shrink mid-sentence (same rules as ui/overlay.py). Positions are physical pixels.</summary>
sealed class CaptionsWindow : Window
{
    const int LineChars = 80;          // characters per line
    const double HideAfter = 10;       // hide after 10 s without speech
    const int BottomGap = 70;          // default distance from the bottom of the screen

    readonly MainWindow main;
    readonly nint hwnd;
    readonly FontIcon handle = new() { Glyph = "", FontSize = 18, Foreground = new SolidColorBrush(Palette.Rgb(0x4D4D52)) };
    readonly TextBlock label = new()
    {
        FontFamily = new FontFamily("Cascadia Mono, Consolas"), Foreground = new SolidColorBrush(Palette.Text),
        TextWrapping = TextWrapping.NoWrap, VerticalAlignment = VerticalAlignment.Center,
    };
    readonly Grid root;
    bool clickThrough, buttonWasDown, overHandle, shown, placed;
    PointInt32? position;            // where the bar is, once placed
    string history = "", live = "";
    DateTime lastChange = DateTime.MinValue;
    bool previewing;

    /// <summary>Recording with the captions turned on.</summary>
    public bool Wanted { get; set; }

    public CaptionsWindow(MainWindow main)
    {
        this.main = main;
        Title = "Laiaudio captions";
        var bar = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 12 };
        handle.VerticalAlignment = VerticalAlignment.Center;
        ToolTipService.SetToolTip(handle, "Drag to move");
        bar.Children.Add(handle);
        bar.Children.Add(label);
        root = new Grid
        {
            Background = new SolidColorBrush(Palette.Base), Padding = new Thickness(12, 10, 18, 10),
            HorizontalAlignment = HorizontalAlignment.Left, VerticalAlignment = VerticalAlignment.Top,
        };
        root.Children.Add(bar);
        root.SizeChanged += (_, _) => { if (shown) Resize(); };
        Content = root;

        hwnd = WinRT.Interop.WindowNative.GetWindowHandle(this);
        var presenter = OverlappedPresenter.CreateForToolWindow();
        presenter.SetBorderAndTitleBar(false, false);
        presenter.IsResizable = false;
        presenter.IsAlwaysOnTop = true;
        AppWindow.SetPresenter(presenter);
        AppWindow.IsShownInSwitchers = false;
        var style = (long)Win32.GetWindowLongPtr(hwnd, Win32.GWL_EXSTYLE);
        style = (style | Win32.WS_EX_TOPMOST | Win32.WS_EX_TOOLWINDOW | Win32.WS_EX_NOACTIVATE | Win32.WS_EX_LAYERED)
                & ~Win32.WS_EX_APPWINDOW;
        Win32.SetWindowLongPtr(hwnd, Win32.GWL_EXSTYLE, (nint)style);
        Win32.SetLayeredWindowAttributes(hwnd, 0, 235, 2);  // Base at ~90 % (LWA_ALPHA)
        int round = 2, border = 0x003C3A3A;                  // DWMWCP_ROUND; the Border color as 0x00BBGGRR
        Win32.DwmSetWindowAttribute(hwnd, 33, ref round, sizeof(int));
        Win32.DwmSetWindowAttribute(hwnd, 34, ref border, sizeof(int));
        SetClickThrough(true);
        ApplyStyle();

        Ui.Every(TimeSpan.FromMilliseconds(50), () => { FollowPointer(); return true; });
        Ui.Every(TimeSpan.FromSeconds(1), () => { AutoHide(); TrackPosition(); return true; });
    }

    JsonObject Config => main.Config;

    int Lines => (int?)Config["overlay_lines"] ?? 2;

    double Scale => Win32.GetDpiForWindow(hwnd) / 96.0;

    public void ApplyStyle()
    {
        label.FontSize = (int?)Config["overlay_font_size"] ?? 22;
        // Always 80 characters wide and the chosen number of lines tall, so the bar keeps its size
        label.LineHeight = Math.Ceiling(label.FontSize * 1.35);
        label.LineStackingStrategy = LineStackingStrategy.BlockLineHeight;
        var sample = new TextBlock { Text = new string('M', LineChars), FontFamily = label.FontFamily, FontSize = label.FontSize };
        sample.Measure(new Windows.Foundation.Size(double.PositiveInfinity, double.PositiveInfinity));
        label.Width = Math.Ceiling(sample.DesiredSize.Width);
        label.Height = label.LineHeight * Lines;
        Render();
        if (shown) Resize();
    }

    // --- text ---
    public void Reset()
    {
        history = live = "";
        Render();
    }

    /// <summary>The bar never shrinks mid-sentence (the model sometimes loses its stable words for an instant); it
    /// accepts corrections of equal or greater length, usually 1–2 words.</summary>
    public void SetLive(string stable)
    {
        if (Words(stable) >= Words(live))
        {
            live = stable;
            Render();
        }
    }

    static int Words(string text) => text.Split(' ', StringSplitOptions.RemoveEmptyEntries).Length;

    public void AddCommitted(string text)
    {
        history = $"{history} {text}".Trim();
        live = "";
        var lines = Wrap(history);
        if (lines.Count > 40) history = string.Join(' ', lines.TakeLast(Lines));  // by whole lines: no reflow
        Render();
    }

    /// <summary>Python's textwrap.wrap: lines of up to 80 characters, broken at spaces, long words kept whole.</summary>
    static List<string> Wrap(string text)
    {
        var lines = new List<string>();
        var line = new StringBuilder();
        foreach (var word in text.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries))
        {
            if (line.Length > 0 && line.Length + 1 + word.Length > LineChars)
            {
                lines.Add(line.ToString());
                line.Clear();
            }
            if (line.Length > 0) line.Append(' ');
            line.Append(word);
        }
        if (line.Length > 0) lines.Add(line.ToString());
        return lines;
    }

    /// <summary>Fixed lines: new text goes at the end and, when full, everything moves up one line.</summary>
    public void Render()
    {
        var lines = Wrap($"{history} {live}".Trim()).TakeLast(Lines).ToList();
        bool hasText = lines.Count > 0;
        label.Text = string.Join('\n', lines);
        lastChange = DateTime.Now;
        bool visible = (Wanted || previewing) && hasText;
        if (visible && !shown) ShowBar();
        else if (!visible && shown) HideBar();
    }

    public void Preview()
    {
        if (history.Length == 0 && live.Length == 0) history = "Captions will appear here";
        previewing = true;
        Render();
        Ui.Every(TimeSpan.FromSeconds(1), () =>
        {
            if ((DateTime.Now - lastChange).TotalSeconds < 6) return true;
            previewing = false;
            if (!Wanted) Reset();
            return false;
        });
    }

    void AutoHide()
    {
        if (shown && (DateTime.Now - lastChange).TotalSeconds > HideAfter) Reset();
    }

    // --- placement ---
    void ShowBar()
    {
        shown = true;
        Resize();
        var size = AppWindow.Size;
        position = Fit(position ?? Saved() ?? CenteredOn(DefaultScreen(), size), size);
        AppWindow.Move(position.Value);
        AppWindow.Show(false);  // without taking the focus
        Win32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x1 | 0x2 | 0x10);  // HWND_TOPMOST, NOSIZE | NOMOVE | NOACTIVATE
        Ui.After(TimeSpan.FromMilliseconds(500), () => placed = true);
    }

    void HideBar()
    {
        shown = placed = false;
        AppWindow.Hide();
    }

    /// <summary>The window is exactly the bar (measured before it is shown, then its real size once laid out).</summary>
    void Resize()
    {
        root.Measure(new Windows.Foundation.Size(double.PositiveInfinity, double.PositiveInfinity));
        double width = Math.Max(root.DesiredSize.Width, root.ActualWidth), height = Math.Max(root.DesiredSize.Height, root.ActualHeight);
        double scale = Scale;
        var wanted = new SizeInt32((int)Math.Ceiling(width * scale), (int)Math.Ceiling(height * scale));
        if (wanted.Width != AppWindow.Size.Width || wanted.Height != AppWindow.Size.Height) AppWindow.Resize(wanted);
    }

    Win32.Screen DefaultScreen()
    {
        var screens = Win32.Screens();
        return screens.FirstOrDefault(s => s.Name == (string?)Config["overlay_monitor"]) ?? screens[0];
    }

    PointInt32? Saved() =>
        Config["overlay_position"] is JsonObject saved && saved["x"] is not null && saved["y"] is not null
            ? new PointInt32((int)saved["x"]!, (int)saved["y"]!) : null;

    PointInt32 CenteredOn(Win32.Screen screen, SizeInt32 size)
    {
        var work = screen.Work;
        return new PointInt32(work.Left + Math.Max(0, (work.Right - work.Left - size.Width) / 2),
                              work.Bottom - size.Height - (int)(BottomGap * Scale));
    }

    /// <summary>Keep the whole bar on the screen nearest to it (for example after that screen was disconnected).</summary>
    static PointInt32 Fit(PointInt32 at, SizeInt32 size)
    {
        var center = (X: at.X + size.Width / 2, Y: at.Y + size.Height / 2);
        var screens = Win32.Screens();
        var screen = screens.FirstOrDefault(s => center.X >= s.Bounds.Left && center.X < s.Bounds.Right &&
                                                 center.Y >= s.Bounds.Top && center.Y < s.Bounds.Bottom) ?? screens[0];
        var w = screen.Work;
        return new PointInt32(Math.Min(Math.Max(w.Left, at.X), Math.Max(w.Left, w.Right - size.Width)),
                              Math.Min(Math.Max(w.Top, at.Y), Math.Max(w.Top, w.Bottom - size.Height)));
    }

    /// <summary>The screen changed in Settings: center the bar at the bottom of it and show it briefly.</summary>
    public void MoveToScreen(string name)
    {
        var screen = Win32.Screens().FirstOrDefault(s => s.Name == name) ?? Win32.Screens()[0];
        if (!shown) Resize();
        position = CenteredOn(screen, AppWindow.Size);
        SavePosition();
        if (shown) AppWindow.Move(position.Value);
        Preview();
    }

    /// <summary>Save where the user dropped the bar (Windows moved it, so read it back).</summary>
    void TrackPosition()
    {
        if (!shown || !placed) return;
        var now = AppWindow.Position;
        if (position is { } old && old.X == now.X && old.Y == now.Y) return;
        position = now;
        SavePosition();
    }

    void SavePosition()
    {
        if (position is { } p) main.Set("overlay_position", new JsonObject { ["x"] = p.X, ["y"] = p.Y });
    }

    // --- mouse ---
    void SetClickThrough(bool enabled)
    {
        if (enabled == clickThrough) return;
        clickThrough = enabled;
        var style = (long)Win32.GetWindowLongPtr(hwnd, Win32.GWL_EXSTYLE);
        style = enabled ? style | Win32.WS_EX_TRANSPARENT : style & ~Win32.WS_EX_TRANSPARENT;
        Win32.SetWindowLongPtr(hwnd, Win32.GWL_EXSTYLE, (nint)style);
    }

    /// <summary>Clicks reach the bar only over the drag handle (elsewhere they go to the app below); a press there
    /// drags it. Windows would swallow that press (the bar never takes the focus), so the button is read here.</summary>
    void FollowPointer()
    {
        if (!shown) return;
        Win32.GetCursorPos(out var cursor);
        var origin = handle.TransformToVisual(root).TransformPoint(new Windows.Foundation.Point(0, 0));
        double scale = Scale;
        var pos = AppWindow.Position;
        double left = pos.X + (origin.X - 6) * scale, top = pos.Y + (origin.Y - 6) * scale;
        double right = pos.X + (origin.X + handle.ActualWidth + 6) * scale, bottom = pos.Y + (origin.Y + handle.ActualHeight + 6) * scale;
        bool over = cursor.X >= left && cursor.X < right && cursor.Y >= top && cursor.Y < bottom;
        SetClickThrough(!over);
        if (over != overHandle)
        {
            overHandle = over;
            handle.Foreground = new SolidColorBrush(over ? Palette.Text : Palette.Rgb(0x4D4D52));
        }
        bool down = (Win32.GetAsyncKeyState(0x01) & 0x8000) != 0;
        if (over && down && !buttonWasDown)  // pressed on the handle, not dragged over it
        {
            lastChange = DateTime.Now;
            Win32.ReleaseCapture();
            Win32.SendMessage(hwnd, 0x00A1, 2, 0);  // WM_NCLBUTTONDOWN on HTCAPTION: returns on release
            down = false;
        }
        buttonWasDown = down;
    }
}
