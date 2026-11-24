using Microsoft.UI.Text;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Input;
using Microsoft.UI.Xaml.Media;
using Windows.ApplicationModel.DataTransfer;
using Windows.System;

namespace Laiaudio;

/// <summary>Text translator page: paste Spanish to get clear B2 English, or English to get Spanish (local LLM).
/// Keeps the text between visits; the header shows the title.</summary>
sealed class TranslatorView : Grid
{
    static readonly HashSet<string> SpanishWords = ["el", "la", "los", "las", "de", "que", "y", "en", "un", "una",
        "es", "por", "para", "con", "no", "se", "lo", "del", "al", "como", "pero", "más", "este", "esta", "hay",
        "tengo", "quiero"];
    static readonly HashSet<string> EnglishWords = ["the", "and", "is", "to", "of", "a", "in", "that", "it", "for",
        "you", "with", "on", "this", "are", "be", "we", "have", "not", "can", "will", "do", "i", "my", "what"];

    readonly Engine engine;
    readonly TextBox input, output;
    readonly TextBlock direction, status;
    readonly ProgressRing spinner = new() { Width = 20, Height = 20, IsActive = false };
    readonly Button run;
    string? model;  // the local LLM it uses, null when none is downloaded
    bool working;

    public TranslatorView(Engine engine)
    {
        this.engine = engine;
        input = Box(editable: true);
        Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(input, "Text to translate");
        input.TextChanged += (_, _) => UpdateDirection();
        output = Box(editable: false);
        Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(output, "Result");
        direction = Ui.Text("", 14, FontWeights.Bold, Palette.SapphireText);
        direction.VerticalAlignment = VerticalAlignment.Center;
        run = Ui.Primary(new Button { Content = "Translate" });
        ToolTipService.SetToolTip(run, "Translate (Ctrl+Enter)");
        run.Click += (_, _) => Run();
        var actions = new Grid { ColumnSpacing = 10 };
        actions.ColumnDefinitions.Add(new ColumnDefinition());
        actions.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        actions.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        actions.Children.Add(direction);
        Grid.SetColumn(spinner, 1);
        Grid.SetColumn(run, 2);
        actions.Children.Add(spinner);
        actions.Children.Add(run);

        status = Ui.Muted("", 13);
        status.VerticalAlignment = VerticalAlignment.Center;
        var copy = new Button { Content = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8,
                                                           Children = { Ui.Icon(Glyph.Copy), new TextBlock { Text = "Copy" } } } };
        Ui.Flat(copy);
        Microsoft.UI.Xaml.Automation.AutomationProperties.SetName(copy, "Copy");
        copy.Click += (_, _) => Copy();
        var footer = new Grid { ColumnSpacing = 10 };
        footer.ColumnDefinitions.Add(new ColumnDefinition());
        footer.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        footer.Children.Add(status);
        Grid.SetColumn(copy, 1);
        footer.Children.Add(copy);

        var body = new StackPanel { Spacing = 12, Margin = new Thickness(24), MaxWidth = 900 };
        body.Children.Add(Ui.Muted("Paste Spanish to get clear B2 English, or English to get Spanish.", 14));
        body.Children.Add(input);
        body.Children.Add(actions);
        body.Children.Add(output);
        body.Children.Add(footer);
        Children.Add(new ScrollViewer { Content = body, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled });

        var shortcut = new KeyboardAccelerator { Key = VirtualKey.Enter, Modifiers = VirtualKeyModifiers.Control };
        shortcut.Invoked += (_, e) => { Run(); e.Handled = true; };
        KeyboardAccelerators.Add(shortcut);

        engine.On("assist_status", e => status.Text = (string?)e["text"] ?? "");
        engine.On("assist_done", Done);
        UpdateDirection();
    }

    static TextBox Box(bool editable) => new()
    {
        AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, IsReadOnly = !editable, MinHeight = 160,
        FontSize = 15, Padding = new Thickness(14, 12, 14, 12), IsSpellCheckEnabled = editable,
        Background = new SolidColorBrush(Palette.Depth),
    };

    /// <summary>The local LLM the service would use (state.assistant_model).</summary>
    public void SetModel(string? name)
    {
        model = name;
        if (IsLoaded && Visibility == Visibility.Visible) Opened();
    }

    /// <summary>Shown in the workspace: check the model (it may have been downloaded meanwhile) and focus the input.</summary>
    public void Opened()
    {
        if (model is null)
        {
            run.IsEnabled = false;
            status.Text = "Download Qwen3 4B or Gemma 3 4B in Settings → Translation to use the translator.";
        }
        else if (!working)
        {
            run.IsEnabled = true;
            status.Text = "";
        }
        DispatcherQueue.TryEnqueue(() => input.Focus(FocusState.Programmatic));
    }

    /// <summary>Hidden: the service frees the GPU when nobody else uses the AI.</summary>
    public void Closed() => engine.Send("assist_close");

    public static bool LooksSpanish(string text)
    {
        if (text.IndexOfAny("áéíóúñ¿¡".ToCharArray()) >= 0) return true;
        var words = text.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries)
                        .Select(w => w.Trim(".,;:!?\"'()".ToCharArray()).ToLowerInvariant()).ToList();
        return words.Count(SpanishWords.Contains) > words.Count(EnglishWords.Contains);
    }

    void UpdateDirection()
    {
        var text = input.Text.Trim();
        direction.Text = text.Length == 0 ? "" : LooksSpanish(text) ? "Spanish → English (B2)" : "English → Spanish";
    }

    void Run()
    {
        var text = input.Text.Trim();
        if (text.Length == 0 || !run.IsEnabled) return;
        working = true;
        run.IsEnabled = false;
        spinner.IsActive = true;
        engine.Send("assist", new { text });
    }

    void Done(System.Text.Json.Nodes.JsonObject e)
    {
        working = false;
        spinner.IsActive = false;
        run.IsEnabled = model is not null;
        if ((string?)e["error"] is { } error)
            status.Text = $"Could not translate: {error}";
        else
        {
            output.Text = (string?)e["result"] ?? "";
            status.Text = "";
        }
    }

    void Copy()
    {
        if (output.Text.Trim() is not { Length: > 0 } text) return;
        var package = new DataPackage();
        package.SetText(text);
        Clipboard.SetContent(package);
        status.Text = "Copied to the clipboard";
    }
}
