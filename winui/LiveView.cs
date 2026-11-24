using System.Text.RegularExpressions;
using Microsoft.UI.Text;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace Laiaudio;

/// <summary>One speaker turn: English on the left and, when translation is on, Spanish on the right.</summary>
sealed partial class Turn
{
    public const string Meeting = "Meeting", Me = "Me";
    const int MaxParagraph = 600;  // transcript.MAX_PARAGRAPH: a longer turn starts a new paragraph

    [GeneratedRegex(@"[.?!](?=\s|$)")]
    private static partial Regex SentenceEnd();

    static int nextId;

    public readonly int Id = ++nextId;
    public readonly Grid View;
    readonly TextBlock en, es;
    public string Text = "";
    int sent;  // characters of Text already sent for translation

    public Turn(string speaker, double start)
    {
        View = new Grid { ColumnSpacing = 32, RowSpacing = 4 };
        View.ColumnDefinitions.Add(new ColumnDefinition());
        View.ColumnDefinitions.Add(new ColumnDefinition());
        View.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        View.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        var when = DateTimeOffset.FromUnixTimeMilliseconds((long)(start * 1000)).ToLocalTime();
        View.Children.Add(Header($"{when:HH:mm:ss}  ·  {speaker}", speaker));
        en = Body(Palette.Text, 1);
        es = Body(Palette.Text, 0.72);
        Grid.SetRow(en, 1);
        Grid.SetRow(es, 1);
        Grid.SetColumn(es, 1);
        View.Children.Add(en);
        View.Children.Add(es);
    }

    public static TextBlock Header(string text, string speaker) =>
        Ui.Text(text, 12.5, FontWeights.Bold, Meetings.MeLabels.Contains(speaker) ? Palette.Carbon : Palette.SapphireText);

    public static TextBlock Body(Windows.UI.Color color, double opacity)
    {
        var text = Ui.Text("", 16, color: color, opacity: opacity);
        text.IsTextSelectionEnabled = true;
        return text;
    }

    public bool Long => Text.Length > MaxParagraph;

    public bool Translated
    {
        set
        {
            es.Visibility = value ? Visibility.Visible : Visibility.Collapsed;
            Grid.SetColumnSpan(en, value ? 1 : 2);
        }
    }

    public void Append(string text)
    {
        Text = $"{Text} {text}".Trim();
        en.Text = Text;
    }

    /// <summary>The complete sentences not translated yet (or everything left when the turn closed).</summary>
    public string Untranslated(bool final)
    {
        var rest = Text[sent..];
        int cut = final ? rest.Length : SentenceEnd().Matches(rest).Select(m => m.Index + m.Length).DefaultIfEmpty(0).Max();
        sent += cut;
        return rest[..cut].Trim();
    }

    public void AddTranslation(string text) => es.Text = $"{es.Text} {text}".Trim();
}

/// <summary>Live transcript: one block per turn and, at the bottom, what is being said right now.</summary>
sealed class LiveView : Grid
{
    readonly ScrollViewer scroll = new() { HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled };
    readonly StackPanel done = new() { Spacing = 18 }, live = new() { Spacing = 6 };
    readonly Grid column;
    readonly List<Turn> turns = new();
    readonly Dictionary<string, Turn> open = new();        // speaker -> open turn
    readonly Dictionary<int, Turn> byId = new();
    readonly Dictionary<string, TextBlock> liveLabels = new();
    readonly Action<int, string> translate;
    bool translating;

    public LiveView(Action<int, string> translate)
    {
        this.translate = translate;
        var stack = new StackPanel { Spacing = 18, Margin = new Thickness(24) };
        stack.Children.Add(done);
        stack.Children.Add(live);
        column = new Grid { MaxWidth = 900, HorizontalAlignment = HorizontalAlignment.Stretch };
        column.Children.Add(stack);
        scroll.Content = column;
        Children.Add(scroll);
    }

    public bool IsEmpty => turns.Count == 0;

    public void Clear()
    {
        done.Children.Clear();
        live.Children.Clear();
        turns.Clear();
        open.Clear();
        byId.Clear();
        liveLabels.Clear();
    }

    /// <summary>Translation turned on or off: show the Spanish column and translate what is already there.</summary>
    public void SetTranslating(bool on)
    {
        translating = on;
        column.MaxWidth = on ? 1600 : 900;
        foreach (var turn in turns)
        {
            turn.Translated = on;
            Translate(turn, final: !open.ContainsValue(turn));
        }
    }

    void Translate(Turn turn, bool final)
    {
        if (translating && turn.Untranslated(final) is { Length: > 0 } text)
            translate(turn.Id, text);
    }

    public void AddTranslation(int id, string text)
    {
        if (byId.TryGetValue(id, out var turn)) turn.AddTranslation(text);
    }

    public void AddCommitted(string speaker, double start, string text, bool endOfTurn)
    {
        open.TryGetValue(speaker, out var turn);
        if (turn is null && text.Length > 0)
        {
            turn = new Turn(speaker, start) { Translated = translating };
            turns.Add(turn);
            byId[turn.Id] = turn;
            done.Children.Add(turn.View);
            open[speaker] = turn;
        }
        if (text.Length > 0) turn!.Append(text);
        if (turn is not null && (endOfTurn || turn.Long))
        {
            open.Remove(speaker);
            Translate(turn, final: true);
        }
        else if (turn is not null) Translate(turn, final: false);
        ScrollToEnd();
    }

    public void SetPartial(string speaker, string text)
    {
        if (!liveLabels.TryGetValue(speaker, out var label))
        {
            label = Ui.Text("", 16, opacity: 0.55);
            liveLabels[speaker] = label;
            live.Children.Add(label);
        }
        label.Text = text.Length > 0 ? $"{speaker}: {text}" : "";
        label.Visibility = text.Length > 0 ? Visibility.Visible : Visibility.Collapsed;
        ScrollToEnd();
    }

    void ScrollToEnd() =>
        DispatcherQueue.TryEnqueue(Microsoft.UI.Dispatching.DispatcherQueuePriority.Low,
                                   () => scroll.ChangeView(null, scroll.ScrollableHeight, null, true));
}
