using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using Microsoft.UI.Dispatching;

namespace Laiaudio;

/// <summary>The Python engine (python -m laiaudio.service): commands go to its stdin and events come back on its
/// stdout, one JSON object per line. Events are raised on the UI thread.</summary>
sealed class Engine
{
    public static string DataDir { get; } =
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Laiaudio");

    readonly DispatcherQueue ui;
    readonly Process process;
    readonly Dictionary<string, List<Action<JsonObject>>> handlers = new();

    /// <summary>The service stopped (after "quit", or because it failed).</summary>
    public event Action? Exited;

    public Engine(DispatcherQueue ui)
    {
        this.ui = ui;
        // LAIAUDIO_PYTHON and LAIAUDIO_SOURCE let a development build run the repository's Python code
        var python = Environment.GetEnvironmentVariable("LAIAUDIO_PYTHON") ??
                     Path.Combine(DataDir, "venv", "Scripts", "python.exe");
        var info = new ProcessStartInfo(python, "-m laiaudio.service")
        {
            UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = DataDir,
            RedirectStandardInput = true, RedirectStandardOutput = true,
            StandardInputEncoding = new UTF8Encoding(false), StandardOutputEncoding = Encoding.UTF8,
        };
        if (Environment.GetEnvironmentVariable("LAIAUDIO_SOURCE") is { } source)
            info.Environment["PYTHONPATH"] = source;
        info.Environment["PYTHONUTF8"] = "1";
        Directory.CreateDirectory(DataDir);
        process = Process.Start(info) ?? throw new InvalidOperationException("Could not start the engine");
        Win32.KillWithApp(process);
        new Thread(Read) { IsBackground = true, Name = "engine-events" }.Start();
    }

    public void On(string name, Action<JsonObject> handler)
    {
        if (!handlers.TryGetValue(name, out var list)) handlers[name] = list = new();
        list.Add(handler);
    }

    public void Send(string command, object? data = null)
    {
        var message = data is null ? new JsonObject() : JsonSerializer.SerializeToNode(data)!.AsObject();
        message["cmd"] = command;
        try
        {
            lock (process)
            {
                process.StandardInput.WriteLine(message.ToJsonString());
                process.StandardInput.Flush();
            }
        }
        catch (IOException)
        {
            // the service already stopped: Exited reports it
        }
    }

    public bool WaitForExit(int milliseconds) => process.WaitForExit(milliseconds);

    void Read()
    {
        while (process.StandardOutput.ReadLine() is { } line)
        {
            JsonObject? message;
            try { message = JsonNode.Parse(line)?.AsObject(); }
            catch (JsonException) { continue; }
            if (message?["event"]?.GetValue<string>() is not { } name) continue;
            ui.TryEnqueue(() =>
            {
                if (handlers.TryGetValue(name, out var list))
                    foreach (var handler in list) handler(message);
            });
        }
        ui.TryEnqueue(() => Exited?.Invoke());
    }
}
