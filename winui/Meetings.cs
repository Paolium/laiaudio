using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace Laiaudio;

/// <summary>Saved meetings: the Markdown files in the transcript folder (same rules as ui/meeting_view.py).</summary>
static partial class Meetings
{
    // Automatic headings (the Spanish ones come from transcripts made before the English UI)
    [GeneratedRegex(@"^(?:Meeting|Reunión) — (\d{4}-\d{2}-\d{2} \d{2}:\d{2})$")]
    private static partial Regex DefaultHeading();

    [GeneratedRegex(@"^\*\*\[(\d{2}:\d{2}:\d{2})\] (.+?):\*\* (.*)$")]
    public static partial Regex Turn();

    [GeneratedRegex(@"^_(?:End|Fin): (.+)_$")]
    public static partial Regex End();

    public static readonly HashSet<string> MeLabels = ["Me", "Yo"];

    public static IEnumerable<string> List(string folder) =>
        Directory.Exists(folder)
            ? Directory.GetFiles(folder, "*.md").OrderByDescending(Path.GetFileName, StringComparer.Ordinal)
            : [];

    public static string Read(string path) => File.ReadAllText(path, Encoding.UTF8);

    /// <summary>The title is the .md heading; when it is the automatic one, the date is shown instead.</summary>
    public static string Title(string path)
    {
        string first;
        using (var reader = new StreamReader(path, Encoding.UTF8))
            first = (reader.ReadLine() ?? "").Trim();
        var heading = first.StartsWith("# ") ? first[2..].Trim() : "";
        var match = DefaultHeading().Match(heading);
        if (heading.Length > 0 && !match.Success) return heading;
        var culture = CultureInfo.InvariantCulture;
        if (match.Success && DateTime.TryParseExact(match.Groups[1].Value, "yyyy-MM-dd HH:mm", culture,
                                                    DateTimeStyles.None, out var when) ||
            DateTime.TryParseExact(Path.GetFileNameWithoutExtension(path), "yyyy-MM-dd_HH-mm", culture,
                                   DateTimeStyles.None, out when))
            return when.ToString("MMM dd, yyyy  HH:mm", culture);
        return Path.GetFileNameWithoutExtension(path);
    }

    public static void Rename(string path, string title)
    {
        var text = Read(path);
        var heading = $"# {title}\n";
        var lines = text.Split('\n').ToList();
        if (lines.Count > 0 && lines[0].StartsWith("# "))
            text = heading + string.Join('\n', lines.Skip(1));
        else
            text = heading + "\n" + text;
        File.WriteAllText(path, text, new UTF8Encoding(false));
    }

    /// <summary>The first sentence said, for the sidebar.</summary>
    public static string Preview(string text)
    {
        foreach (var line in text.Split('\n'))
            if (line.StartsWith("**["))
            {
                var said = line.Split(":**", 2) is [_, var rest] ? rest.Trim() : line;
                return said.Length > 80 ? said[..80] : said;
            }
        return "";
    }
}
