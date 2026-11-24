using System.Numerics;
using Microsoft.UI;
using Microsoft.UI.Text;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Documents;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Animation;
using Microsoft.UI.Xaml.Shapes;
using Windows.UI;

namespace Laiaudio;

/// <summary>Segoe Fluent Icons glyphs used by the app.</summary>
static class Glyph
{
    public const string Microphone = "", Captions = "", Settings = "", Copy = "",
        Edit = "", Folder = "", Delete = "", Pane = "", Download = "";
}

/// <summary>Small builders for the controls every page uses.</summary>
static class Ui
{
    static readonly HashSet<Microsoft.UI.Dispatching.DispatcherQueueTimer> timers = new();

    /// <summary>A UI-thread timer that stays alive while it runs (an unreferenced one is collected and stops).
    /// The callback returns whether to keep running.</summary>
    public static void Every(TimeSpan interval, Func<bool> tick)
    {
        var timer = Microsoft.UI.Dispatching.DispatcherQueue.GetForCurrentThread().CreateTimer();
        timer.Interval = interval;
        timer.Tick += (t, _) =>
        {
            if (tick()) return;
            t.Stop();
            timers.Remove(t);
        };
        timers.Add(timer);
        timer.Start();
    }

    public static void After(TimeSpan delay, Action action) => Every(delay, () => { action(); return false; });

    public static FontIcon Icon(string glyph, double size = 16) => new() { Glyph = glyph, FontSize = size };

    public static TextBlock Text(string text, double size = 14, Windows.UI.Text.FontWeight? weight = null, Color? color = null,
                                 double opacity = 1) =>
        new()
        {
            Text = text, FontSize = size, FontWeight = weight ?? FontWeights.Normal, TextWrapping = TextWrapping.Wrap,
            Foreground = new SolidColorBrush(color ?? Palette.Text), Opacity = opacity,
        };

    public static TextBlock Muted(string text, double size = 13) => Text(text, size, color: Palette.Muted);

    /// <summary>Text with &lt;b&gt;bold&lt;/b&gt; parts (the descriptions of the status page use them).</summary>
    public static TextBlock Markup(string markup, double size = 14)
    {
        var block = Text("", size);
        block.TextAlignment = TextAlignment.Center;
        var parts = markup.Split(["<b>", "</b>"], StringSplitOptions.None);
        for (int i = 0; i < parts.Length; i++)
            if (parts[i].Length > 0)
                block.Inlines.Add(new Run { Text = parts[i], FontWeight = i % 2 == 1 ? FontWeights.Bold : FontWeights.Normal });
        return block;
    }

    public static Button IconButton(string glyph, string tooltip, Action action, Color? hover = null)
    {
        var button = new Button { Content = Icon(glyph), Padding = new Thickness(10, 6, 10, 6) };
        Flat(button);
        ToolTipService.SetToolTip(button, tooltip);
        AutomationProperties.SetName(button, tooltip);
        button.Click += (_, _) => action();
        if (hover is { } color)
        {
            button.Resources["ButtonForegroundPointerOver"] = new SolidColorBrush(color);
            button.Resources["ButtonForegroundPressed"] = new SolidColorBrush(color);
        }
        return button;
    }

    /// <summary>Primary button (Start, Translate, Download): Sapphire with white text, as on Linux. Windows' own
    /// accent button in dark mode is the lighter accent with dark text.</summary>
    public static Button Primary(Button button)
    {
        foreach (var (state, background, foreground) in new[] { ("", 0x0D71FDu, 0xFFu), ("PointerOver", 0x3D8BFDu, 0xFFu),
                                                                ("Pressed", 0x0A5ACBu, 0xE6u) })
        {
            button.Resources[$"AccentButtonBackground{state}"] = new SolidColorBrush(Palette.Rgb(background));
            button.Resources[$"AccentButtonBorderBrush{state}"] = new SolidColorBrush(Palette.Rgb(background));
            button.Resources[$"AccentButtonForeground{state}"] = new SolidColorBrush(Palette.Rgb(0xFFFFFF, (byte)foreground));
        }
        button.Style = null;  // the template reads its brushes when the style is applied
        button.Style = (Style)Application.Current.Resources["AccentButtonStyle"];
        return button;
    }

    /// <summary>No background or border until the pointer is over it (like a toolbar button).</summary>
    public static T Flat<T>(T button) where T : Control
    {
        button.Background = new SolidColorBrush(Colors.Transparent);
        button.BorderThickness = new Thickness(0);
        button.Resources["ButtonBackground"] = new SolidColorBrush(Colors.Transparent);
        button.Resources["ButtonBackgroundDisabled"] = new SolidColorBrush(Colors.Transparent);
        button.Resources["ToggleButtonBackground"] = new SolidColorBrush(Colors.Transparent);
        return button;
    }

    /// <summary>Rounded group of buttons on Base with a Border outline (docs/design.md, "Pill bar").</summary>
    public static Border PillBar(params UIElement[] children)
    {
        var row = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 2 };
        foreach (var child in children) row.Children.Add(child);
        return new Border
        {
            Child = row, Background = new SolidColorBrush(Palette.Base), BorderBrush = new SolidColorBrush(Palette.Border),
            BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(18), Padding = new Thickness(3),
        };
    }

    public static Ellipse Dot(Color color) =>
        new() { Width = 10, Height = 10, Fill = new SolidColorBrush(color), VerticalAlignment = VerticalAlignment.Center };

    /// <summary>A soft, endless 1.6 s pulse (the recording dot).</summary>
    public static Storyboard Pulse(UIElement target)
    {
        var animation = new DoubleAnimation
        {
            From = 1, To = 0.35, Duration = TimeSpan.FromSeconds(0.8), AutoReverse = true,
            RepeatBehavior = RepeatBehavior.Forever, EasingFunction = new SineEase { EasingMode = EasingMode.EaseInOut },
        };
        Storyboard.SetTarget(animation, target);
        Storyboard.SetTargetProperty(animation, "Opacity");
        var story = new Storyboard();
        story.Children.Add(animation);
        return story;
    }

    /// <summary>Settings group: a title, an optional description and its cards.</summary>
    public static StackPanel Group(string title, string? description, params UIElement[] cards)
    {
        var group = new StackPanel { Spacing = 4, Margin = new Thickness(0, 0, 0, 24) };
        group.Children.Add(Text(title, 14, FontWeights.SemiBold));
        if (description is not null)
        {
            var text = Muted(description);
            text.Margin = new Thickness(0, 0, 0, 6);
            group.Children.Add(text);
        }
        else group.Children.Add(new Border { Height = 4 });
        foreach (var card in cards) group.Children.Add(card);
        return group;
    }

    /// <summary>Settings card like Windows 11 Settings: title and subtitle on the left, the control on the right.</summary>
    public static Border Card(string title, string? subtitle, UIElement? control, out TextBlock titleBlock,
                              out TextBlock subtitleBlock)
    {
        var grid = new Grid { ColumnSpacing = 16, MinHeight = 48 };
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        var texts = new StackPanel { VerticalAlignment = VerticalAlignment.Center, Spacing = 2 };
        titleBlock = Text(title);
        subtitleBlock = Muted(subtitle ?? "", 12);
        subtitleBlock.Visibility = string.IsNullOrEmpty(subtitle) ? Visibility.Collapsed : Visibility.Visible;
        texts.Children.Add(titleBlock);
        texts.Children.Add(subtitleBlock);
        grid.Children.Add(texts);
        if (control is FrameworkElement element)
        {
            if (title.Length > 0 && string.IsNullOrEmpty(AutomationProperties.GetName(element)))
                AutomationProperties.SetName(element, title);  // screen readers name the control after its card
            element.VerticalAlignment = VerticalAlignment.Center;
            Grid.SetColumn(element, 1);
            grid.Children.Add(element);
        }
        return new Border
        {
            Child = grid, Background = new SolidColorBrush(Palette.Surface), BorderBrush = new SolidColorBrush(Palette.Border),
            BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(6), Padding = new Thickness(16, 10, 16, 10),
            Margin = new Thickness(0, 0, 0, 3),
        };
    }

    public static Border Card(string title, string? subtitle, UIElement? control) =>
        Card(title, subtitle, control, out _, out _);

    /// <summary>The page bar below the header (on Base): a start and an end part, or one centered part.</summary>
    public static Grid PageBar(UIElement? start = null, UIElement? end = null, UIElement? center = null)
    {
        var bar = new Grid { Padding = new Thickness(16, 8, 16, 8), Background = new SolidColorBrush(Palette.Base) };
        foreach (var (child, align) in new[] { (start, HorizontalAlignment.Left), (center, HorizontalAlignment.Center),
                                               (end, HorizontalAlignment.Right) })
            if (child is FrameworkElement element)
            {
                element.HorizontalAlignment = align;
                bar.Children.Add(element);
            }
        return bar;
    }
}

/// <summary>Background-less on/off toggle: the icon (or text) turns colored when on and gets a diagonal slash when
/// off (docs/design.md, "StateToggle").</summary>
sealed class StateToggle : Button
{
    readonly FrameworkElement content;
    readonly Line slash;
    readonly Color on, onHover, offHover;
    bool active, hovered;

    public event Action<bool>? Toggled;

    public StateToggle(string tooltip, bool active, Color on, Color onHover, Color? offHover = null,
                       string? glyph = null, string? label = null)
    {
        this.on = on;
        this.onHover = onHover;
        this.offHover = offHover ?? Palette.Text;
        this.active = active;
        content = glyph is not null ? Ui.Icon(glyph) : Ui.Text(label!, 14, FontWeights.Bold);
        content.RenderTransformOrigin = new Windows.Foundation.Point(0.5, 0.5);
        slash = new Line
        {
            X1 = 2, Y1 = 16, X2 = 16, Y2 = 2, StrokeThickness = 1.7, StrokeStartLineCap = PenLineCap.Round,
            StrokeEndLineCap = PenLineCap.Round, HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Center, IsHitTestVisible = false,
        };
        var grid = new Grid { Width = 28, Height = 22 };
        grid.Children.Add(content);
        content.HorizontalAlignment = HorizontalAlignment.Center;
        content.VerticalAlignment = VerticalAlignment.Center;
        grid.Children.Add(slash);
        Content = grid;
        Padding = new Thickness(8, 4, 8, 4);
        CornerRadius = new CornerRadius(14);
        Ui.Flat(this);
        Resources["ButtonBackgroundPointerOver"] = new SolidColorBrush(Colors.Transparent);
        Resources["ButtonBackgroundPressed"] = new SolidColorBrush(Colors.Transparent);
        ToolTipService.SetToolTip(this, tooltip);
        AutomationProperties.SetName(this, tooltip);
        Click += (_, _) => { IsOn = !IsOn; Toggled?.Invoke(IsOn); };
        PointerEntered += (_, _) => { hovered = true; Paint(); };
        PointerExited += (_, _) => { hovered = false; Paint(); };
        IsEnabledChanged += (_, _) => Paint();
        Paint();
    }

    public bool IsOn
    {
        get => active;
        set { active = value; Paint(); }
    }

    void Paint()
    {
        Color color = active ? (hovered ? onHover : on) : (hovered ? offHover : Palette.Text);
        double opacity = active || hovered ? 1 : 0.55;
        if (!IsEnabled) opacity *= 0.5;
        var brush = new SolidColorBrush(color) { Opacity = opacity };
        if (content is FontIcon icon) icon.Foreground = brush;
        else ((TextBlock)content).Foreground = brush;
        slash.Stroke = brush;
        slash.Visibility = active ? Visibility.Collapsed : Visibility.Visible;
        content.RenderTransform = new ScaleTransform { ScaleX = active && hovered ? 1.12 : 1, ScaleY = active && hovered ? 1.12 : 1 };
    }
}

/// <summary>Short notices at the bottom of the window (native InfoBars), with an optional action; each closes
/// itself after 6 s.</summary>
sealed class Toasts : StackPanel
{
    public Toasts()
    {
        Spacing = 6;
        HorizontalAlignment = HorizontalAlignment.Center;
        VerticalAlignment = VerticalAlignment.Bottom;
        Margin = new Thickness(16, 0, 16, 16);
        MaxWidth = 640;
    }

    public void Show(string text, string? button = null, Action? action = null)
    {
        var bar = new InfoBar
        {
            Message = text, IsOpen = true, IsClosable = true, Severity = InfoBarSeverity.Informational,
            IsIconVisible = false, Background = new SolidColorBrush(Palette.Surface),
            Translation = new Vector3(0, 0, 24), Shadow = new ThemeShadow(),
        };
        if (button is not null && action is not null)
        {
            var actionButton = new Button { Content = button };
            actionButton.Click += (_, _) => { action(); bar.IsOpen = false; };
            bar.ActionButton = actionButton;
        }
        bar.Closed += (_, _) => Children.Remove(bar);
        Children.Add(bar);
        while (Children.Count > 3) Children.RemoveAt(0);
        Ui.After(TimeSpan.FromSeconds(6), () => bar.IsOpen = false);
    }
}
