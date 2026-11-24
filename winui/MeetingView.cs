using System.Diagnostics;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.ApplicationModel.DataTransfer;

namespace Laiaudio;

/// <summary>Saved meeting: a sticky bar with the view modes and actions, and the .md as a preview or as Markdown.
/// The header shows the title.</summary>
sealed class MeetingView : Grid
{
    readonly MainWindow window;
    readonly StackPanel preview = new() { Spacing = 18, Margin = new Thickness(24), MaxWidth = 900 };
    readonly TextBlock source = new()
    {
        FontFamily = new FontFamily("Cascadia Mono, Consolas"), FontSize = 13, TextWrapping = TextWrapping.Wrap,
        IsTextSelectionEnabled = true, Margin = new Thickness(24), Foreground = new SolidColorBrush(Palette.Text),
    };
    readonly ScrollViewer previewPage, sourcePage;
    public string? Path { get; private set; }

    public MeetingView(MainWindow window)
    {
        this.window = window;
        RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        RowDefinitions.Add(new RowDefinition());

        var modes = new SelectorBar();
        var previewItem = new SelectorBarItem { Text = "Preview", IsSelected = true };
        var sourceItem = new SelectorBarItem { Text = "Markdown" };
        modes.Items.Add(previewItem);
        modes.Items.Add(sourceItem);
        modes.SelectionChanged += (bar, _) =>
        {
            bool showPreview = bar.SelectedItem == previewItem;
            previewPage!.Visibility = showPreview ? Visibility.Visible : Visibility.Collapsed;
            sourcePage!.Visibility = showPreview ? Visibility.Collapsed : Visibility.Visible;
        };
        var actions = Ui.PillBar(
            Ui.IconButton(Glyph.Copy, "Copy all text", CopyAll, Palette.SapphireText),
            Ui.IconButton(Glyph.Edit, "Edit title", () => _ = EditTitle(), Palette.SapphireText),
            Ui.IconButton(Glyph.Folder, "Show the .md file in File Explorer", ShowInExplorer, Palette.SapphireText),
            Ui.IconButton(Glyph.Delete, "Delete", () => _ = Delete(), Palette.Ruby));
        Children.Add(Ui.PageBar(modes, actions));

        previewPage = new ScrollViewer { Content = preview, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled };
        sourcePage = new ScrollViewer { Content = source, Visibility = Visibility.Collapsed };
        foreach (var page in new[] { previewPage, sourcePage })
        {
            SetRow(page, 1);
            Children.Add(page);
        }
    }

    public void Load(string path)
    {
        Path = path;
        var text = Meetings.Read(path);
        source.Text = text;
        preview.Children.Clear();
        foreach (var raw in text.Split('\n'))
            PreviewLine(raw.Trim());
        previewPage.ChangeView(null, 0, null, true);
    }

    public void Forget() => Path = null;

    void PreviewLine(string line)
    {
        if (line.Length == 0 || line.StartsWith("# ")) return;  // the title is already in the header
        if (Meetings.Turn().Match(line) is { Success: true } turn)
        {
            var box = new StackPanel { Spacing = 4 };
            var speaker = turn.Groups[2].Value;
            box.Children.Add(Turn.Header($"{turn.Groups[1].Value}  ·  {speaker}", speaker));
            var said = Turn.Body(Palette.Text, 1);
            said.Text = turn.Groups[3].Value;
            box.Children.Add(said);
            preview.Children.Add(box);
        }
        else if (Meetings.End().Match(line) is { Success: true } end)
            preview.Children.Add(Ui.Muted($"End: {end.Groups[1].Value}", 14));
        else
        {
            var text = Ui.Text(line);
            text.IsTextSelectionEnabled = true;
            preview.Children.Add(text);
        }
    }

    void CopyAll()
    {
        if (Path is null) return;
        var package = new DataPackage();
        package.SetText(Meetings.Read(Path));
        Clipboard.SetContent(package);
        window.Toast("Text copied to the clipboard");
    }

    void ShowInExplorer()
    {
        if (Path is not null) Process.Start("explorer.exe", $"/select,\"{Path}\"");
    }

    async Task EditTitle()
    {
        if (Path is not { } path) return;
        var entry = new TextBox { Text = Meetings.Title(path), SelectionStart = 0 };
        entry.SelectAll();
        var dialog = new ContentDialog
        {
            Title = "Meeting title", Content = entry, PrimaryButtonText = "Save", CloseButtonText = "Cancel",
            DefaultButton = ContentDialogButton.Primary, XamlRoot = XamlRoot,
        };
        // Enter presses the default button (Save)
        if (await dialog.ShowAsync() == ContentDialogResult.Primary && entry.Text.Trim() is { Length: > 0 } title)
        {
            Meetings.Rename(path, title);
            window.MeetingChanged(path);
        }
    }

    async Task Delete()
    {
        if (Path is not { } path) return;
        var dialog = new ContentDialog
        {
            Title = "Delete this meeting?", Content = $"“{Meetings.Title(path)}” will be moved to the Recycle Bin.",
            PrimaryButtonText = "Delete", CloseButtonText = "Cancel", DefaultButton = ContentDialogButton.None,
            XamlRoot = XamlRoot,
        };
        dialog.PrimaryButtonStyle = new Style(typeof(Button));
        dialog.PrimaryButtonStyle.Setters.Add(new Setter(Control.BackgroundProperty, new SolidColorBrush(Palette.Ruby)));
        dialog.PrimaryButtonStyle.Setters.Add(new Setter(Control.ForegroundProperty, new SolidColorBrush(Microsoft.UI.Colors.White)));
        if (await dialog.ShowAsync() != ContentDialogResult.Primary) return;
        if (Win32.Recycle(path)) window.MeetingDeleted(path);
        else window.Toast("Could not move the meeting to the Recycle Bin");
    }
}
