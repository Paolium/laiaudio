using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.UI;
using Microsoft.UI.Input;
using Microsoft.UI.Text;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Documents;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Animation;
using Microsoft.UI.Xaml.Media.Imaging;
using Microsoft.UI.Xaml.Shapes;
using Windows.Graphics;

namespace Laiaudio;

/// <summary>Main window: saved meetings on the left, the header (in Windows' own title bar, with its native
/// minimize, maximize and close), the workspace and the footer. Same structure and rules as ui/main_window.py.</summary>
public sealed class MainWindow : Window
{
    const string Status = "status", Live = "live", File = "file", Translator = "translator", Settings = "settings";
    static readonly string[] Covers = [Translator, Settings];  // pages that sit on top of the others

    readonly Engine engine;
    internal JsonObject? State { get; private set; }
    internal JsonObject Config { get; private set; } = new();
    internal CaptionsWindow Captions { get; }

    // sidebar
    readonly SplitView split = new() { DisplayMode = SplitViewDisplayMode.Inline, OpenPaneLength = 280, IsPaneOpen = true };
    readonly StackPanel brand = new() { Padding = new Thickness(0, 14, 0, 10), Spacing = 4 };
    readonly AutoSuggestBox search = new() { PlaceholderText = "Search by title or content", Margin = new Thickness(8, 0, 8, 8),
                                             QueryIcon = new SymbolIcon(Symbol.Find) };
    readonly ListView meetings = new() { SelectionMode = ListViewSelectionMode.Single, IsItemClickEnabled = true };
    ListViewItem translatorItem = null!, liveItem = null!;
    Ellipse translatorDot = null!, liveDot = null!;
    Storyboard? livePulse;

    // header and live bar
    readonly Grid header = new() { Height = 48, Background = new SolidColorBrush(Palette.Depth) };
    readonly Button sidebarButton, recordButton = new() { Content = "Start", IsEnabled = false, MinWidth = 64 };
    readonly TextBlock title = new() { FontSize = 14, FontWeight = FontWeights.Bold, VerticalAlignment = VerticalAlignment.Center,
                                       HorizontalAlignment = HorizontalAlignment.Center, TextTrimming = TextTrimming.CharacterEllipsis,
                                       Foreground = new SolidColorBrush(Palette.Text) };
    readonly StateToggle micButton, overlayButton, esButton;
    readonly Grid liveBar;

    // workspace
    readonly Grid workspace = new();
    readonly Dictionary<string, FrameworkElement> pages = new();
    readonly StackPanel statusPage = new() { HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center,
                                             Spacing = 12, MaxWidth = 680, Margin = new Thickness(24) };
    readonly LiveView live;
    readonly MeetingView meeting;
    readonly TranslatorView translator;
    readonly SettingsView settings;
    readonly Toasts toasts = new();
    ModelCard? missingCard;
    string current = Status, behind = Status;  // behind: the page a cover hides

    bool engineReady, recording, saving, quitting, firstState = true;
    double started;

    public MainWindow()
    {
        Title = "Laiaudio";
        engine = new Engine(DispatcherQueue);
        Captions = new CaptionsWindow(this);
        live = new LiveView((id, text) => engine.Send("translate_turn", new { id, text }));
        meeting = new MeetingView(this);
        translator = new TranslatorView(engine);
        settings = new SettingsView(this, engine);

        sidebarButton = Ui.IconButton(Glyph.Pane, "Show or hide the meetings", () => SetSidebar(!split.IsPaneOpen));
        micButton = new StateToggle("Also transcribe your microphone", true, Palette.Ruby, Palette.RubyLight, glyph: Glyph.Microphone);
        micButton.Toggled += on => SetUseMic(on);
        overlayButton = new StateToggle("Floating captions", true, Palette.SapphireText, Palette.SapphireLight,
                                        Palette.SapphireText, glyph: Glyph.Captions);
        overlayButton.Toggled += on => SetOverlayEnabled(on);
        esButton = new StateToggle("Translate into Spanish (right column)", false, Palette.SapphireText, Palette.SapphireLight,
                                   Palette.SapphireText, label: "ES");
        esButton.Toggled += on => { Config["translation_active"] = on; engine.Send("translation", new { active = on }); };
        liveBar = Ui.PageBar(end: Ui.PillBar(micButton, overlayButton, esButton));

        Content = Build();
        SetUpTitleBar();
        Listen();
        Single.Activated += () => DispatcherQueue.TryEnqueue(() =>
        {
            if (AppWindow.Presenter is OverlappedPresenter { State: OverlappedPresenterState.Minimized } p) p.Restore();
            Activate();
        });
        AppWindow.Closing += OnClosing;
        Ui.Every(TimeSpan.FromSeconds(1), () => { if (recording) UpdateTitle(); return true; });
        RefreshMeetings();
        ShowStatus("Loading…", "");
    }

    // --- layout ---
    UIElement Build()
    {
        // Sidebar: brand, search, translator, live and saved meetings, and Settings at the bottom
        var logo = new Image { Source = new SvgImageSource(new Uri(System.IO.Path.Combine(AppContext.BaseDirectory, "Assets", "paolium-logo.svg"))),
                               Width = 64, Height = 64 };
        brand.Children.Add(logo);
        brand.Children.Add(new TextBlock { Text = "Laiaudio", FontWeight = FontWeights.SemiBold, FontSize = 15,
                                           HorizontalAlignment = HorizontalAlignment.Center, CharacterSpacing = -20 });
        search.TextChanged += (_, _) => Filter();
        // ClickedItem is the row itself or its content, depending on how the row was hit
        meetings.ItemClick += (_, e) => OnMeetingClicked(e.ClickedItem as ListViewItem ??
            meetings.Items.OfType<ListViewItem>().First(i => i.Content == e.ClickedItem));
        var settingsButton = new Button
        {
            Content = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8,
                                       Children = { Ui.Icon(Glyph.Settings), new TextBlock { Text = "Settings", FontWeight = FontWeights.SemiBold } } },
            HorizontalAlignment = HorizontalAlignment.Center, Margin = new Thickness(6),
        };
        Ui.Flat(settingsButton);
        Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(settingsButton, "Settings");
        settingsButton.Click += (_, _) => OpenSettings();
        var sidebar = new Grid { Background = new SolidColorBrush(Palette.Depth) };
        foreach (var height in new[] { GridLength.Auto, GridLength.Auto, new GridLength(1, GridUnitType.Star), GridLength.Auto })
            sidebar.RowDefinitions.Add(new RowDefinition { Height = height });
        sidebar.Children.Add(brand);
        Grid.SetRow(search, 1);
        Grid.SetRow(meetings, 2);
        Grid.SetRow(settingsButton, 3);
        sidebar.Children.Add(search);
        sidebar.Children.Add(meetings);
        sidebar.Children.Add(settingsButton);
        split.Pane = sidebar;
        split.PaneBackground = new SolidColorBrush(Palette.Depth);
        split.PaneOpening += (_, _) => UpdateDragRegions();
        split.PaneClosed += (_, _) => UpdateDragRegions();

        // Header: sidebar toggle, Start/Stop and the page title; Windows draws minimize, maximize and close
        var left = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 6, Margin = new Thickness(8, 0, 0, 0),
                                    VerticalAlignment = VerticalAlignment.Center };
        left.Children.Add(sidebarButton);
        left.Children.Add(recordButton);
        Ui.Primary(recordButton);
        recordButton.Click += (_, _) => engine.Send(recording ? "stop" : "start");
        header.Children.Add(title);
        header.Children.Add(left);
        header.SizeChanged += (_, _) => UpdateDragRegions();
        title.Margin = new Thickness(220, 0, 220, 0);

        // Workspace pages
        statusPage.Children.Add(new FontIcon { Glyph = Glyph.Microphone, FontSize = 96, Foreground = Palette.Brush(Palette.Text, 0.5) });
        pages[Status] = new ScrollViewer { Content = statusPage };
        pages[Live] = live;
        pages[File] = meeting;
        pages[Translator] = translator;
        pages[Settings] = settings;
        foreach (var page in pages.Values)
        {
            page.Visibility = Visibility.Collapsed;
            workspace.Children.Add(page);
        }
        pages[Status].Visibility = Visibility.Visible;

        var content = new Grid { Background = new SolidColorBrush(Palette.Base) };
        foreach (var height in new[] { GridLength.Auto, GridLength.Auto, new GridLength(1, GridUnitType.Star), GridLength.Auto })
            content.RowDefinitions.Add(new RowDefinition { Height = height });
        content.Children.Add(header);
        Grid.SetRow(liveBar, 1);
        Grid.SetRow(workspace, 2);
        var footer = Footer();
        Grid.SetRow(footer, 3);
        Grid.SetRow(toasts, 1);
        Grid.SetRowSpan(toasts, 2);
        content.Children.Add(liveBar);
        content.Children.Add(workspace);
        content.Children.Add(footer);
        content.Children.Add(toasts);
        split.Content = content;
        return split;
    }

    static Grid Footer()
    {
        var link = new HyperlinkButton
        {
            Content = new TextBlock { Text = "Paolium", FontWeight = FontWeights.SemiBold, CharacterSpacing = -20,
                                      Foreground = new SolidColorBrush(Palette.Text) },
            NavigateUri = new Uri("https://paolium.web.app/"), Padding = new Thickness(4, 0, 0, 0),
        };
        var row = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Center };
        var designed = Ui.Text("Designed by", 11.5);
        designed.VerticalAlignment = VerticalAlignment.Center;
        var dot = Ui.Text(".", 14, FontWeights.SemiBold, Palette.Gold);
        dot.VerticalAlignment = VerticalAlignment.Center;
        row.Children.Add(designed);
        row.Children.Add(link);
        row.Children.Add(dot);
        var footer = new Grid
        {
            Background = new SolidColorBrush(Palette.Depth), Padding = new Thickness(16, 4, 16, 4),
            BorderBrush = new SolidColorBrush(Palette.Border), BorderThickness = new Thickness(0, 1, 0, 0),
        };
        footer.Children.Add(row);
        return footer;
    }

    /// <summary>The header lives in Windows' title bar: Windows draws minimize, maximize and close (with Snap
    /// Layouts) and moves the window from the empty parts of the header and of the sidebar brand.</summary>
    void SetUpTitleBar()
    {
        ExtendsContentIntoTitleBar = true;
        var bar = AppWindow.TitleBar;
        bar.PreferredHeightOption = TitleBarHeightOption.Tall;
        bar.ButtonBackgroundColor = Colors.Transparent;
        bar.ButtonInactiveBackgroundColor = Colors.Transparent;
        bar.ButtonForegroundColor = Palette.Text;
        bar.ButtonInactiveForegroundColor = Palette.Rgb(0xD6DAE0, 0x73);
        bar.ButtonHoverBackgroundColor = Palette.Rgb(0xFFFFFF, 0x17);
        bar.ButtonHoverForegroundColor = Colors.White;
        bar.ButtonPressedBackgroundColor = Palette.Rgb(0xFFFFFF, 0x0F);
        bar.ButtonPressedForegroundColor = Palette.Text;
        AppWindow.SetIcon(System.IO.Path.Combine(AppContext.BaseDirectory, "Assets", "laiaudio.ico"));

        // 1000 × 700 like the Linux window, centered on the screen
        var area = DisplayArea.GetFromWindowId(AppWindow.Id, DisplayAreaFallback.Primary).WorkArea;
        double scale = Win32.GetDpiForWindow(WinRT.Interop.WindowNative.GetWindowHandle(this)) / 96.0;
        int width = (int)(1000 * scale), height = (int)(700 * scale);
        AppWindow.MoveAndResize(new RectInt32(area.X + (area.Width - width) / 2, area.Y + (area.Height - height) / 2, width, height));
    }

    void UpdateDragRegions()
    {
        if (Content?.XamlRoot is not { } root) return;
        double scale = root.RasterizationScale;
        RectInt32 Rect(FrameworkElement element)
        {
            var at = element.TransformToVisual(null).TransformPoint(new Windows.Foundation.Point(0, 0));
            return new RectInt32((int)(at.X * scale), (int)(at.Y * scale), (int)(element.ActualWidth * scale),
                                 (int)(element.ActualHeight * scale));
        }
        var caption = new List<RectInt32> { Rect(header) };
        if (split.IsPaneOpen) caption.Add(Rect(brand));
        var source = InputNonClientPointerSource.GetForWindowId(AppWindow.Id);
        source.SetRegionRects(NonClientRegionKind.Caption, caption.ToArray());
        source.SetRegionRects(NonClientRegionKind.Passthrough, [Rect(sidebarButton), Rect(recordButton)]);
    }

    // --- engine events ---
    void Listen()
    {
        engine.On("state", e =>
        {
            State = e;
            Config = e["config"]!.AsObject();
            if (firstState)
            {
                firstState = false;
                SetSidebar((bool)Config["sidebar_visible"]!, save: false);
                micButton.IsOn = (bool)Config["use_mic"]!;
                overlayButton.IsOn = (bool)Config["overlay_enabled"]!;
                Captions.ApplyStyle();
                RefreshMeetings();
            }
            settings.Refresh();
            translator.SetModel((string?)e["assistant_model"]);
            if (missingCard is not null && Model((string?)e["engine"]?["model_id"]) is { } model) missingCard.SetModel(model);
        });
        engine.On("engine", ApplyEngine);
        engine.On("toast", e => Toast((string)e["text"]!, (string?)e["button"], e["action"] as JsonObject));
        engine.On("translation", e =>
        {
            bool active = (bool)e["active"]!;
            Config["translation_active"] = active;
            esButton.IsOn = active;
            live.SetTranslating(active);
        });
        engine.On("turn_translation", e => live.AddTranslation((int)e["id"]!, (string)e["text"]!));
        engine.On("recording", e => OnRecording((string)e["state"]!, e));
        engine.On("partial", e =>
        {
            string speaker = (string)e["speaker"]!, text = (string)e["text"]!;
            live.SetPartial(speaker, text);
            if (speaker == Turn.Meeting) Captions.SetLive(text);
        });
        engine.On("committed", e =>
        {
            string speaker = (string)e["speaker"]!, text = (string)e["text"]!;
            live.AddCommitted(speaker, (double)e["start"]!, text, (bool)e["end_of_turn"]!);
            if (speaker == Turn.Meeting && text.Length > 0) Captions.AddCommitted(text);
        });
        engine.On("download", e => missingCard?.OnDownload(e));
        engine.Exited += () =>
        {
            engineStopped = true;
            if (quitting)
            {
                Captions.Close();
                Close();
                Application.Current.Exit();
                return;
            }
            recordButton.IsEnabled = false;
            ShowStatus("The engine stopped", $"Its log is in {System.IO.Path.Combine(Engine.DataDir, "app.log")}");
        };
    }

    JsonObject? Model(string? id) =>
        State?["models"]?.AsArray().Select(m => m!.AsObject()).FirstOrDefault(m => (string?)m["id"] == id);

    void ApplyEngine(JsonObject e)
    {
        var status = (string)e["status"]!;
        engineReady = status == "ready";
        missingCard = null;
        switch (status)
        {
            case "missing":
                recordButton.IsEnabled = false;
                missingCard = settings.NewCard();
                if (Model((string?)e["model_id"]) is { } model) missingCard.SetModel(model);
                var other = new HyperlinkButton { Content = "Choose another model", HorizontalAlignment = HorizontalAlignment.Center };
                other.Click += (_, _) => OpenSettings("transcription");
                var box = new StackPanel { Spacing = 12 };
                box.Children.Add(missingCard.View);
                box.Children.Add(other);
                ShowStatus("The transcription model is missing", "Download it once; after that everything works offline.", box);
                break;
            case "loading":
                recordButton.IsEnabled = false;
                ShowStatus("Loading model…", $"{e["model"]} is getting ready");
                break;
            case "error":
                recordButton.IsEnabled = false;
                ShowStatus("Could not load the model", (string?)e["detail"] ?? "");
                break;
            default:
                ShowLive();
                break;
        }
    }

    void OnRecording(string state, JsonObject e)
    {
        switch (state)
        {
            case "started":
                recording = true;
                started = (double)e["started"]!;
                live.Clear();
                CloseCover();
                meetings.SelectedItem = liveItem;
                Show(Live);
                recordButton.Content = "Stop";
                Destructive(recordButton);
                micButton.IsEnabled = false;
                SetRecordingDot(true);
                Captions.Reset();
                UpdateCaptions();
                UpdateTitle();
                break;
            case "saving":
                recording = false;
                saving = true;
                recordButton.IsEnabled = false;
                recordButton.Content = "Saving…";
                break;
            case "saved":
                saving = false;
                recordButton.Content = "Start";
                Ui.Primary(recordButton);
                recordButton.IsEnabled = engineReady && !quitting;
                micButton.IsEnabled = true;
                SetRecordingDot(false);
                UpdateTitle();
                UpdateCaptions();
                RefreshMeetings();
                meetings.SelectedItem = liveItem;
                if (live.IsEmpty) ShowLive();  // nothing was said: back to "Ready"
                break;
        }
    }

    /// <summary>Stop: Ruby, like the destructive buttons on Linux.</summary>
    static void Destructive(Button button)
    {
        foreach (var (state, color) in new[] { ("", 0xFA4F67u), ("PointerOver", 0xFC6A7Fu), ("Pressed", 0xE0465Cu) })
        {
            button.Resources[$"AccentButtonBackground{state}"] = new SolidColorBrush(Palette.Rgb(color));
            button.Resources[$"AccentButtonBorderBrush{state}"] = new SolidColorBrush(Palette.Rgb(color));
        }
        // the template caches its brushes: re-apply the style so the new ones are read
        button.Style = null;
        button.Style = (Style)Application.Current.Resources["AccentButtonStyle"];
    }

    // --- settings shared with the live bar ---
    internal void Set(string key, object? value)
    {
        Config[key] = value as JsonNode ?? JsonSerializer.SerializeToNode(value);
        engine.Send("set", new { key, value = Config[key]?.DeepClone() });
    }

    internal void SetOverlayEnabled(bool enabled)
    {
        Set("overlay_enabled", enabled);
        overlayButton.IsOn = enabled;
        UpdateCaptions();
        settings.Refresh();
    }

    internal void SetUseMic(bool enabled)
    {
        Set("use_mic", enabled);
        micButton.IsOn = enabled;
        settings.Refresh();
    }

    void SetSidebar(bool visible, bool save = true)
    {
        split.IsPaneOpen = visible;
        if (save) Set("sidebar_visible", visible);
        DispatcherQueue.TryEnqueue(UpdateDragRegions);
    }

    void UpdateCaptions()
    {
        Captions.Wanted = recording && ((bool?)Config["overlay_enabled"] ?? true);
        Captions.Render();
    }

    // --- workspace pages ---
    bool CoverOpen => Covers.Contains(current);

    /// <summary>Switch page, or queue it behind the translator or settings while one is open.</summary>
    void Show(string name)
    {
        if (CoverOpen) behind = name;
        else SetPage(name);
    }

    void SetPage(string name)
    {
        if (name == current && pages[name].Visibility == Visibility.Visible) return;
        var previous = current;
        pages[current].Visibility = Visibility.Collapsed;
        pages[name].Visibility = Visibility.Visible;
        current = name;
        if (name == Translator) translator.Opened();
        else if (previous == Translator) translator.Closed();
        if (!Covers.Contains(name)) behind = name;
        OnPageChanged();
    }

    void CloseCover()
    {
        if (CoverOpen) SetPage(behind);
    }

    void OpenSettings(string? tab = null)
    {
        settings.Load(tab);
        SetPage(Settings);
    }

    /// <summary>Title, the live bar and the translator row follow the page.</summary>
    void OnPageChanged()
    {
        UpdateTitle();
        liveBar.Visibility = current is Status or Live ? Visibility.Visible : Visibility.Collapsed;
        if (current != Live && !(recording || saving) && !live.IsEmpty) ResetLive();
        UpdateTranslatorRow();
    }

    /// <summary>The header title follows the page: translator, settings, the open meeting, the timer while
    /// recording or "New meeting".</summary>
    void UpdateTitle()
    {
        title.Inlines.Clear();
        if (current is Translator or Settings)
            title.Text = current == Translator ? "Translator" : "Settings";
        else if (current == File && meeting.Path is { } path)
            title.Text = Meetings.Title(path);
        else if (recording)
        {
            var secs = (int)(DateTimeOffset.Now.ToUnixTimeMilliseconds() / 1000.0 - started);
            title.Inlines.Add(new Run { Text = "● ", Foreground = new SolidColorBrush(Palette.Ruby) });
            title.Inlines.Add(new Run { Text = $"{secs / 3600:00}:{secs % 3600 / 60:00}:{secs % 60:00}" });
        }
        else title.Text = "New meeting";
    }

    void ShowStatus(string heading, string description, UIElement? child = null)
    {
        while (statusPage.Children.Count > 1) statusPage.Children.RemoveAt(1);
        var text = Ui.Text(heading, 28, FontWeights.Bold);
        text.TextAlignment = TextAlignment.Center;
        statusPage.Children.Add(text);
        if (description.Length > 0)
        {
            var markup = Ui.Markup(description);
            markup.Opacity = 0.85;
            statusPage.Children.Add(markup);
        }
        if (child is not null) statusPage.Children.Add(child);
        Show(Status);
    }

    void ShowLive()
    {
        bool empty = live.IsEmpty && !recording;
        if (empty && engineReady)
        {
            recordButton.IsEnabled = !saving && !quitting;
            ShowStatus("Ready", "Press <b>Start</b> when the meeting begins");
        }
        else if (!empty) Show(Live);
    }

    /// <summary>Leaving a finished recording: it is already saved, so "Live" starts again from "Ready".</summary>
    void ResetLive()
    {
        live.Clear();
        if (CoverOpen) ShowLive();  // updates the page behind the translator or settings
    }

    /// <summary>The translator dot turns sapphire while the translator is open; closing it selects the row behind.</summary>
    void UpdateTranslatorRow()
    {
        if (current == Translator)
        {
            translatorDot.Fill = new SolidColorBrush(Palette.SapphireText);
            meetings.SelectedItem = translatorItem;
        }
        else
        {
            translatorDot.Fill = Palette.Brush(Palette.Text, 0.45);
            if (ReferenceEquals(meetings.SelectedItem, translatorItem)) SelectMeeting(behind == File ? meeting.Path : null);
        }
    }

    // --- saved meetings ---
    internal void RefreshMeetings()
    {
        meetings.Items.Clear();
        translatorItem = Row("Translator", null, out translatorDot, Palette.SapphireText);
        ToolTipService.SetToolTip(translatorItem, "Spanish → clear English, English → Spanish");
        liveItem = Row("Live", null, out liveDot, Palette.Ruby);
        liveDot.Fill = new SolidColorBrush(Palette.Text);
        livePulse = null;
        SetRecordingDot(recording);
        meetings.Items.Add(translatorItem);
        meetings.Items.Add(liveItem);
        var folder = (string?)Config["meetings_dir"];
        foreach (var path in folder is null ? [] : Meetings.List(folder))
        {
            string text;
            try { text = Meetings.Read(path); }
            catch (IOException) { continue; }
            var name = Meetings.Title(path);
            var item = Row(name, Meetings.Preview(text), out _, null);
            item.Tag = new MeetingRow(path, $"{name}\n{text}".ToLowerInvariant());
            meetings.Items.Add(item);
        }
        Filter();
        UpdateTranslatorRow();  // the rows are new: restore the dot and the selection
        if (meetings.SelectedItem is null && current != Translator)
            SelectMeeting(current == File || behind == File ? meeting.Path : null);
    }

    sealed record MeetingRow(string Path, string SearchText);

    ListViewItem Row(string name, string? subtitle, out Ellipse dot, Windows.UI.Color? hover)
    {
        var grid = new Grid { ColumnSpacing = 12, Padding = new Thickness(4, 8, 4, 8) };
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        grid.ColumnDefinitions.Add(new ColumnDefinition());
        dot = Ui.Dot(Palette.Rgb(0xD6DAE0, 0x73));
        var texts = new StackPanel { Spacing = 2, VerticalAlignment = VerticalAlignment.Center };
        texts.Children.Add(new TextBlock { Text = name, TextTrimming = TextTrimming.CharacterEllipsis, FontSize = 14 });
        if (subtitle is not null)
        {
            texts.Children.Add(new TextBlock { Text = subtitle, TextTrimming = TextTrimming.CharacterEllipsis, FontSize = 12,
                                               Foreground = new SolidColorBrush(Palette.Muted) });
            grid.ColumnDefinitions[0].Width = new GridLength(0);
            grid.ColumnSpacing = 0;
        }
        else grid.Children.Add(dot);
        Grid.SetColumn(texts, 1);
        grid.Children.Add(texts);
        var item = new ListViewItem { Content = grid, Margin = new Thickness(4, 0, 4, 0) };
        if (hover is { } color)
        {
            var target = dot;
            item.PointerEntered += (_, _) => { if (!IsRecordingDot(target)) target.Fill = new SolidColorBrush(color); };
            item.PointerExited += (_, _) => { if (!IsRecordingDot(target)) ResetDot(target); };
        }
        return item;
    }

    bool IsRecordingDot(Ellipse dot) => dot == liveDot && recording || dot == translatorDot && current == Translator;

    void ResetDot(Ellipse dot)
    {
        if (dot == liveDot) dot.Fill = new SolidColorBrush(Palette.Text);
        else dot.Fill = Palette.Brush(Palette.Text, 0.45);
    }

    /// <summary>The "Live" dot turns red and pulses softly while recording.</summary>
    void SetRecordingDot(bool on)
    {
        if (liveDot is null) return;
        livePulse?.Stop();
        livePulse = null;
        liveDot.Opacity = 1;
        liveDot.Fill = new SolidColorBrush(on ? Palette.Ruby : Palette.Text);
        if (on)
        {
            livePulse = Ui.Pulse(liveDot);
            livePulse.Begin();
        }
    }

    void Filter()
    {
        var words = search.Text.Trim().ToLowerInvariant().Split(' ', StringSplitOptions.RemoveEmptyEntries);
        foreach (var item in meetings.Items.OfType<ListViewItem>())
            if (item.Tag is MeetingRow row)
                item.Visibility = words.All(row.SearchText.Contains) ? Visibility.Visible : Visibility.Collapsed;
    }

    void OnMeetingClicked(ListViewItem item)
    {
        if (item == translatorItem)
        {
            SetPage(Translator);
            return;
        }
        CloseCover();  // picking a meeting leaves the translator or settings
        if (item.Tag is MeetingRow row)
        {
            meeting.Load(row.Path);
            Show(File);
            UpdateTitle();
        }
        else ShowLive();
    }

    /// <summary>Select a saved meeting's row; null selects "Live".</summary>
    void SelectMeeting(string? path)
    {
        meetings.SelectedItem = path is null ? liveItem :
            meetings.Items.OfType<ListViewItem>().FirstOrDefault(i => i.Tag is MeetingRow row && row.Path == path) ?? liveItem;
    }

    /// <summary>Renamed: refresh the list and the view without losing the selection.</summary>
    internal void MeetingChanged(string path)
    {
        RefreshMeetings();
        SelectMeeting(path);
        if (meeting.Path == path)
        {
            meeting.Load(path);
            UpdateTitle();
        }
        Toast("Title updated");
    }

    internal void MeetingDeleted(string path)
    {
        if (meeting.Path == path)
        {
            // Leave the deleted meeting first: its page and the header title read the file
            meeting.Forget();
            ShowLive();
            if (current == File) SetPage(Status);  // the model is still loading: show its status instead
        }
        RefreshMeetings();
        if (meeting.Path is null) meetings.SelectedItem = liveItem;
        Toast("Meeting moved to the Recycle Bin");
    }

    // --- notices ---
    internal void Toast(string text, string? button = null, JsonObject? action = null)
    {
        Action? run = action switch
        {
            null => null,
            _ when (string?)action["ui"] == "settings" => () => OpenSettings((string?)action["tab"]),
            _ when (string?)action["ui"] == "open" => () => Open((string)action["path"]!),
            _ when (string?)action["cmd"] is { } cmd => () => engine.Send(cmd, Without(action, "cmd")),
            _ => null,
        };
        toasts.Show(text, button, run);
    }

    static JsonObject Without(JsonObject source, string key)
    {
        var copy = source.DeepClone().AsObject();
        copy.Remove(key);
        return copy;
    }

    static void Open(string path) => Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });

    // --- closing ---
    /// <summary>Closing saves the meeting first; the window closes once the engine stopped.</summary>
    void OnClosing(AppWindow sender, AppWindowClosingEventArgs args)
    {
        if (engineStopped) return;
        args.Cancel = true;
        if (quitting) return;
        quitting = true;
        if (recording) OnRecording("saving", new JsonObject());
        engine.Send("quit");
        Ui.After(TimeSpan.FromSeconds(30), Application.Current.Exit);  // the engine never answered
    }

    bool engineStopped;
}
