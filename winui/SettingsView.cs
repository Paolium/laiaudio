using System.Text.Json.Nodes;
using Microsoft.UI.Text;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.Storage.Pickers;

namespace Laiaudio;

/// <summary>Model card: its strength and trade-off, plus Download / progress / Ready / Delete.</summary>
sealed class ModelCard
{
    public readonly Border View;
    readonly Engine engine;
    readonly TextBlock title, subtitle;
    readonly ProgressBar progress = new() { Width = 160, Maximum = 1 };
    readonly TextBlock percent = Ui.Muted("", 12);
    readonly Button cancel = new() { Content = "Cancel" };
    readonly Button download = Ui.Primary(new Button());
    readonly TextBlock ready = Ui.Text("✓ Ready", 14, color: Palette.Carbon);
    readonly Button delete;
    readonly StackPanel progressBox = new() { Orientation = Orientation.Horizontal, Spacing = 8 };
    JsonObject? model;
    string? error;  // the last failed download, shown until the next one starts

    public string? Id => (string?)model?["id"];

    public ModelCard(Engine engine)
    {
        this.engine = engine;
        delete = Ui.IconButton(Glyph.Delete, "Delete the downloaded model", () => _ = ConfirmDelete(), Palette.Ruby);
        ready.VerticalAlignment = VerticalAlignment.Center;
        progress.VerticalAlignment = VerticalAlignment.Center;
        percent.VerticalAlignment = VerticalAlignment.Center;
        progressBox.Children.Add(progress);
        progressBox.Children.Add(percent);
        var actions = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        foreach (var element in new UIElement[] { progressBox, cancel, download, ready, delete }) actions.Children.Add(element);
        download.Click += (_, _) => { error = null; engine.Send("download", new { id = Id }); };
        cancel.Click += (_, _) => engine.Send("cancel_download", new { id = Id });
        View = Ui.Card("", "", actions, out title, out subtitle);
        title.FontWeight = FontWeights.SemiBold;
    }

    public void SetModel(JsonObject model)
    {
        this.model = model;
        bool installed = (bool)model["installed"]!, downloading = (bool)model["downloading"]!;
        bool downloadable = (bool)model["downloadable"]!;
        var problem = (string?)model["problem"];
        title.Text = (string)model["name"]! + ((bool)model["recommended"]! ? "  ·  Recommended for your machine" : "");
        var needs = new List<string>();
        if ((string?)model["hardware"] is { Length: > 0 } hardware) needs.Add($"Requires: {hardware}");
        if (downloadable) needs.Add($"Size {model["size_label"]}");
        var lines = new List<string> { (string)model["gains"]!, (string)model["loses"]! };
        if (needs.Count > 0) lines.Add(string.Join("  ·  ", needs));
        if (problem is not null) lines.Add($"⚠ {problem}");
        if (error is not null && !installed) lines.Add($"⚠ Download failed: {error}");
        subtitle.Text = string.Join("\n", lines.Select(line => $"•  {line}"));
        subtitle.Visibility = Visibility.Visible;
        progressBox.Visibility = cancel.Visibility = Show(downloading);
        download.Visibility = Show(!downloading && !installed && problem is null);
        download.Content = $"Download ({model["size_label"]})";
        ready.Visibility = delete.Visibility = Show(installed && downloadable && !downloading);
        Progress((double)model["progress"]!);
    }

    static Visibility Show(bool visible) => visible ? Visibility.Visible : Visibility.Collapsed;

    public void OnDownload(JsonObject e)
    {
        if ((string?)e["id"] != Id || model is null) return;
        if ((bool)e["done"]!)
        {
            error = (string?)e["error"];  // the state that follows refreshes the rest
            return;
        }
        progressBox.Visibility = cancel.Visibility = Visibility.Visible;
        download.Visibility = Visibility.Collapsed;
        Progress((double)e["progress"]!);
    }

    void Progress(double fraction)
    {
        progress.Value = fraction;
        percent.Text = $"{fraction:P0}";
    }

    async Task ConfirmDelete()
    {
        if (model is null) return;
        var dialog = new ContentDialog
        {
            Title = $"Delete {model["name"]}?",
            Content = $"This frees {model["size_label"]}. You can download it again at any time.",
            PrimaryButtonText = "Delete", CloseButtonText = "Cancel", DefaultButton = ContentDialogButton.None,
            XamlRoot = View.XamlRoot,
        };
        if (await dialog.ShowAsync() == ContentDialogResult.Primary) engine.Send("delete_model", new { id = Id });
    }
}

/// <summary>Settings page: tabs for General, Audio, Transcription and Translation in a centered bar, rebuilt
/// every time the page opens so devices, screens and models are always current. The header shows the title.</summary>
sealed class SettingsView : Grid
{
    readonly MainWindow window;
    readonly Engine engine;
    readonly SelectorBar tabs = new();
    readonly ScrollViewer content = new() { HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled };
    readonly Dictionary<string, StackPanel> pages = new();
    readonly Dictionary<string, (ComboBox Picker, ModelCard Card)> pickers = new();
    readonly List<ModelCard> cards = new();
    ComboBox? meetingAudio, microphone;
    readonly List<string> outputIds = [], inputIds = [];
    TextBlock? runOnSubtitle, hardwareTitle, hardwareSubtitle, folderSubtitle;
    ToggleSwitch? overlaySwitch, micSwitch;
    bool updating;  // ignore the changes made by the code itself

    public SettingsView(MainWindow window, Engine engine)
    {
        this.window = window;
        this.engine = engine;
        RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        RowDefinitions.Add(new RowDefinition());
        foreach (var (name, label) in new[] { ("general", "General"), ("audio", "Audio"),
                                               ("transcription", "Transcription"), ("translation", "Translation") })
            tabs.Items.Add(new SelectorBarItem { Text = label, Tag = name });
        tabs.SelectionChanged += (_, _) => ShowTab((string)tabs.SelectedItem.Tag);
        Children.Add(Ui.PageBar(center: tabs));
        SetRow(content, 1);
        Children.Add(content);
        engine.On("devices", Devices);
        engine.On("download", e => { foreach (var card in cards) card.OnDownload(e); });
    }

    JsonObject Config => window.Config;

    public void Load(string? tab)
    {
        pages.Clear();
        pickers.Clear();
        cards.Clear();
        pages["general"] = GeneralPage();
        pages["audio"] = AudioPage();
        pages["transcription"] = ModelPage("asr", "Transcription model", "Turns English speech into text");
        pages["translation"] = ModelPage("translation", "Translation engine", "What appears in the Spanish column (ES button)");
        Refresh();
        tab ??= "general";
        var item = tabs.Items.First(i => (string)i.Tag == tab);
        if (tabs.SelectedItem == item) ShowTab(tab);
        else tabs.SelectedItem = item;
        engine.Send("devices");
    }

    void ShowTab(string name)
    {
        if (pages.TryGetValue(name, out var page))
        {
            content.Content = page;
            content.ChangeView(null, 0, null, true);
        }
    }

    static StackPanel Page() => new() { Margin = new Thickness(24, 16, 24, 24), MaxWidth = 920 };

    // --- General ---
    StackPanel GeneralPage()
    {
        var page = Page();
        var state = window.State;
        bool cuda = (bool?)state?["hardware"]?["cuda"] ?? false;
        var note = cuda ? "" : " · Laiaudio is optimized for NVIDIA GPUs: on this machine transcription uses the Lite model on the CPU";
        var use = new Button { Content = "Use recommended" };
        use.Click += (_, _) => engine.Send("use_recommended");
        page.Children.Add(Ui.Group("Your machine", $"Models that do not fit are marked “won't fit” and cannot be chosen{note}",
                                   Ui.Card("", "", use, out hardwareTitle, out hardwareSubtitle)));

        var change = new Button { Content = "Change" };
        change.Click += (_, _) => _ = ChooseFolder();
        page.Children.Add(Ui.Group("Meetings", null,
                                   Ui.Card("Transcript folder (.md)", (string?)Config["meetings_dir"], change, out _, out folderSubtitle)));

        overlaySwitch = new ToggleSwitch { IsOn = (bool)Config["overlay_enabled"]!, OnContent = "", OffContent = "", MinWidth = 0 };
        overlaySwitch.Toggled += (_, _) => { if (!updating) window.SetOverlayEnabled(overlaySwitch.IsOn); };
        var screens = Win32.Screens();
        var screen = new ComboBox { MinWidth = 220 };
        foreach (var s in screens) screen.Items.Add($"{s.Name}  ({s.Bounds.Right - s.Bounds.Left}×{s.Bounds.Bottom - s.Bounds.Top})");
        var current = (string?)Config["overlay_monitor"];
        screen.SelectedIndex = Math.Max(0, screens.FindIndex(s => s.Name == current));
        screen.SelectionChanged += (_, _) =>
        {
            if (screen.SelectedIndex < 0) return;
            window.Set("overlay_monitor", screens[screen.SelectedIndex].Name);
            window.Captions.MoveToScreen(screens[screen.SelectedIndex].Name);
        };
        page.Children.Add(Ui.Group("Floating captions", null,
            Ui.Card("Show while recording", null, overlaySwitch),
            Ui.Card("Screen", null, screen),
            Ui.Card("Lines", null, Spin("overlay_lines", 1, 4)),
            Ui.Card("Font size", null, Spin("overlay_font_size", 14, 40))));
        return page;
    }

    NumberBox Spin(string key, int min, int max)
    {
        var box = new NumberBox
        {
            Minimum = min, Maximum = max, Value = (double)Config[key]!, SmallChange = 1, MinWidth = 120,
            SpinButtonPlacementMode = NumberBoxSpinButtonPlacementMode.Inline,
        };
        box.ValueChanged += (_, e) =>
        {
            if (double.IsNaN(e.NewValue)) { box.Value = e.OldValue; return; }
            window.Set(key, (int)e.NewValue);
            window.Captions.ApplyStyle();
            window.Captions.Preview();
        };
        return box;
    }

    async Task ChooseFolder()
    {
        var picker = new FolderPicker { SuggestedStartLocation = PickerLocationId.DocumentsLibrary };
        picker.FileTypeFilter.Add("*");
        WinRT.Interop.InitializeWithWindow.Initialize(picker, WinRT.Interop.WindowNative.GetWindowHandle(window));
        if (await picker.PickSingleFolderAsync() is not { } folder) return;  // cancelled
        window.Set("meetings_dir", folder.Path);
        folderSubtitle!.Text = folder.Path;
        window.RefreshMeetings();
    }

    // --- Audio ---
    StackPanel AudioPage()
    {
        var page = Page();
        meetingAudio = new ComboBox { MinWidth = 280, MaxWidth = 420 };
        micSwitch = new ToggleSwitch { IsOn = (bool)Config["use_mic"]!, OnContent = "", OffContent = "", MinWidth = 0 };
        micSwitch.Toggled += (_, _) => { if (!updating) window.SetUseMic(micSwitch.IsOn); };
        microphone = new ComboBox { MinWidth = 280, MaxWidth = 420 };
        foreach (var (combo, key, ids) in new[] { (meetingAudio, "system_source", outputIds), (microphone, "mic_source", inputIds) })
            combo.SelectionChanged += (_, _) =>
            {
                if (!updating && combo.SelectedIndex >= 0 && combo.SelectedIndex < ids.Count) window.Set(key, ids[combo.SelectedIndex]);
            };
        page.Children.Add(Ui.Group("What gets transcribed", "Applies the next time you press Start",
            Ui.Card("Meeting audio", null, meetingAudio),
            Ui.Card("Also transcribe my microphone", "Shows up as “Me”", micSwitch),
            Ui.Card("Microphone", null, microphone)));
        return page;
    }

    void Devices(JsonObject e)
    {
        if (meetingAudio is null || microphone is null) return;
        Fill(meetingAudio, outputIds, "system_source", "Automatic (whatever plays on the default output)", e["outputs"]!.AsArray());
        Fill(microphone, inputIds, "mic_source", "Automatic (default microphone)", e["inputs"]!.AsArray());
    }

    void Fill(ComboBox combo, List<string> ids, string key, string automatic, JsonArray devices)
    {
        updating = true;
        ids.Clear();
        ids.Add("auto");
        combo.Items.Clear();
        combo.Items.Add(automatic);
        foreach (var device in devices)
        {
            ids.Add((string)device![0]!);
            combo.Items.Add((string)device[1]!);
        }
        combo.SelectedIndex = Math.Max(0, ids.IndexOf((string?)Config[key] ?? "auto"));
        updating = false;
    }

    // --- Transcription / Translation ---
    StackPanel ModelPage(string kind, string title, string description)
    {
        var page = Page();
        var picker = new ComboBox { MinWidth = 240 };
        var card = new ModelCard(engine);
        cards.Add(card);
        pickers[kind] = (picker, card);
        picker.SelectionChanged += (_, _) =>
        {
            if (updating || picker.SelectedIndex < 0) return;
            var models = Models(kind);
            engine.Send("pick_model", new { kind, id = (string)models[picker.SelectedIndex]["id"]! });
        };
        page.Children.Add(Ui.Group(title, description, Ui.Card("Model", null, picker), card.View));
        if (kind == "asr")
        {
            var devices = new[] { "auto", "cpu" };
            var runOn = new ComboBox { MinWidth = 160, Items = { "Automatic", "CPU only" } };
            runOn.SelectedIndex = Math.Max(0, Array.IndexOf(devices, (string?)Config["asr_device"]));
            runOn.SelectionChanged += (_, _) => window.Set("asr_device", devices[runOn.SelectedIndex]);
            page.Children.Add(Ui.Group("Hardware", null, Ui.Card("Run on", "", runOn, out _, out runOnSubtitle)));
        }
        return page;
    }

    List<JsonObject> Models(string kind) =>
        window.State?["models"]?.AsArray().Select(m => m!.AsObject()).Where(m => (string?)m["kind"] == kind).ToList() ?? [];

    /// <summary>A new state from the service: models, problems, the recommendation and the engine.</summary>
    public void Refresh()
    {
        var state = window.State;
        if (state is null) return;
        updating = true;
        if (hardwareTitle is not null)
        {
            hardwareTitle.Text = (string?)state["hardware"]?["summary"] ?? "";
            hardwareSubtitle!.Text = $"Recommended: {state["recommended_label"]}";
            hardwareSubtitle.Visibility = Visibility.Visible;
        }
        if (overlaySwitch is not null) overlaySwitch.IsOn = (bool)Config["overlay_enabled"]!;
        if (micSwitch is not null) micSwitch.IsOn = (bool)Config["use_mic"]!;
        if (runOnSubtitle is not null)
        {
            runOnSubtitle.Text = "Automatic uses the NVIDIA GPU when available, otherwise the CPU. " +
                                 state["engine_description"];
            runOnSubtitle.Visibility = Visibility.Visible;
        }
        foreach (var (kind, (picker, card)) in pickers)
        {
            var models = Models(kind);
            // Short name in the list (the full one is on the card) and a mark on the ones that do not fit
            picker.Items.Clear();
            foreach (var m in models)
                picker.Items.Add((string)m["short"]! + (m["problem"] is null ? "" : "  ·  won't fit"));
            var current = (string?)Config[kind == "asr" ? "asr_model" : "translation"];
            int index = Math.Max(0, models.FindIndex(m => (string?)m["id"] == current));
            picker.SelectedIndex = index;
            if (models.Count > 0) card.SetModel(models[index]);
        }
        updating = false;
    }

    /// <summary>The missing-model status page uses the same card.</summary>
    public ModelCard NewCard()
    {
        var card = new ModelCard(engine);
        cards.Add(card);
        return card;
    }
}
