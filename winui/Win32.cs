using System.Runtime.InteropServices;

namespace Laiaudio;

/// <summary>The few Win32 calls WinUI does not cover: job objects, the captions window styles, screens and the
/// Recycle Bin.</summary>
static partial class Win32
{
    // --- child processes die with the app (job object) ---
    [StructLayout(LayoutKind.Sequential)]
    struct BasicLimits
    {
        public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
        public uint LimitFlags;
        public nuint MinimumWorkingSetSize, MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public nuint Affinity;
        public uint PriorityClass, SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct ExtendedLimits
    {
        public BasicLimits Basic;
        public ulong R1, R2, R3, R4, R5, R6;  // IO_COUNTERS
        public nuint ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }

    [LibraryImport("kernel32.dll", EntryPoint = "CreateJobObjectW")]
    private static partial nint CreateJobObject(nint attributes, nint name);

    [LibraryImport("kernel32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool SetInformationJobObject(nint job, int infoClass, ref ExtendedLimits info, int size);

    [LibraryImport("kernel32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool AssignProcessToJobObject(nint job, nint process);

    static nint job;

    /// <summary>Windows kills the process (and what it started, such as llama-server) when the app exits, even
    /// abruptly.</summary>
    public static void KillWithApp(System.Diagnostics.Process process)
    {
        if (job == 0)
        {
            job = CreateJobObject(0, 0);
            var limits = new ExtendedLimits();
            limits.Basic.LimitFlags = 0x2000;  // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            SetInformationJobObject(job, 9, ref limits, Marshal.SizeOf<ExtendedLimits>());
        }
        AssignProcessToJobObject(job, process.Handle);
    }

    // --- windows ---
    public const int GWL_EXSTYLE = -20;
    public const int WS_EX_TOPMOST = 0x8, WS_EX_TRANSPARENT = 0x20, WS_EX_TOOLWINDOW = 0x80,
        WS_EX_APPWINDOW = 0x40000, WS_EX_LAYERED = 0x80000, WS_EX_NOACTIVATE = 0x8000000;

    [LibraryImport("user32.dll", EntryPoint = "GetWindowLongPtrW")]
    public static partial nint GetWindowLongPtr(nint hwnd, int index);

    [LibraryImport("user32.dll", EntryPoint = "SetWindowLongPtrW")]
    public static partial nint SetWindowLongPtr(nint hwnd, int index, nint value);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool SetLayeredWindowAttributes(nint hwnd, uint key, byte alpha, uint flags);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool SetWindowPos(nint hwnd, nint after, int x, int y, int cx, int cy, uint flags);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool ReleaseCapture();

    [LibraryImport("user32.dll", EntryPoint = "SendMessageW")]
    public static partial nint SendMessage(nint hwnd, uint msg, nint wparam, nint lparam);

    [LibraryImport("user32.dll", EntryPoint = "PostMessageW")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool PostMessage(nint hwnd, uint msg, nint wparam, nint lparam);

    [StructLayout(LayoutKind.Sequential)]
    public struct POINT { public int X, Y; }

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool GetCursorPos(out POINT point);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool GetWindowRect(nint hwnd, out RECT rect);

    [LibraryImport("user32.dll")]
    public static partial short GetAsyncKeyState(int key);

    [LibraryImport("user32.dll")]
    public static partial uint GetDpiForWindow(nint hwnd);

    [LibraryImport("dwmapi.dll")]
    public static partial int DwmSetWindowAttribute(nint hwnd, int attribute, ref int value, int size);

    // --- screens ---
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct MonitorInfoEx
    {
        public int Size;
        public RECT Monitor, Work;
        public uint Flags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string Device;
    }

    delegate bool MonitorEnum(nint monitor, nint hdc, nint rect, nint data);

    [DllImport("user32.dll")]
    static extern bool EnumDisplayMonitors(nint hdc, nint clip, MonitorEnum callback, nint data);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern bool GetMonitorInfo(nint monitor, ref MonitorInfoEx info);

    public record Screen(string Name, RECT Bounds, RECT Work, bool Primary);

    /// <summary>Every screen, with the monitor's own name (as the GTK app showed it, for example "M27Q").</summary>
    public static List<Screen> Screens()
    {
        var names = MonitorNames();
        var screens = new List<Screen>();
        EnumDisplayMonitors(0, 0, (monitor, _, _, _) =>
        {
            var info = new MonitorInfoEx { Size = Marshal.SizeOf<MonitorInfoEx>() };
            if (GetMonitorInfo(monitor, ref info))
                screens.Add(new Screen(names.GetValueOrDefault(info.Device, "Screen"), info.Monitor, info.Work,
                                       (info.Flags & 1) != 0));
            return true;
        }, 0);
        return screens.OrderByDescending(s => s.Primary).ToList();
    }

    [StructLayout(LayoutKind.Sequential)]
    struct PathInfo
    {
        public Luid SourceAdapter; public uint SourceId, SourceMode, SourceFlags;
        public Luid TargetAdapter; public uint TargetId, TargetMode, Technology, Rotation, Scaling;
        public uint RefreshNum, RefreshDen, ScanLine, TargetAvailable, TargetFlags, Flags;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct Luid { public uint Low; public int High; }

    [StructLayout(LayoutKind.Sequential)]
    struct ModeInfo { public uint Type, Id; public Luid Adapter; public ulong A, B, C, D, E, F; }

    [StructLayout(LayoutKind.Sequential)]
    struct Header { public int Type, Size; public Luid Adapter; public uint Id; }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct SourceName
    {
        public Header Header;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string Device;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct TargetName
    {
        public Header Header;
        public uint Flags, Technology;
        public ushort Manufacturer, Product;
        public uint ConnectorInstance;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 64)] public string Friendly;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string Path;
    }

    [DllImport("user32.dll")]
    static extern int GetDisplayConfigBufferSizes(uint flags, out uint paths, out uint modes);

    [DllImport("user32.dll")]
    static extern int QueryDisplayConfig(uint flags, ref uint pathCount, [Out] PathInfo[] paths, ref uint modeCount,
                                         [Out] ModeInfo[] modes, nint topology);

    [DllImport("user32.dll", EntryPoint = "DisplayConfigGetDeviceInfo")]
    static extern int GetSourceName(ref SourceName info);

    [DllImport("user32.dll", EntryPoint = "DisplayConfigGetDeviceInfo")]
    static extern int GetTargetName(ref TargetName info);

    /// <summary>\\.\DISPLAY1 → the monitor's name (from its EDID).</summary>
    static Dictionary<string, string> MonitorNames()
    {
        var names = new Dictionary<string, string>();
        const uint activeOnly = 2;
        if (GetDisplayConfigBufferSizes(activeOnly, out var pathCount, out var modeCount) != 0) return names;
        var paths = new PathInfo[pathCount];
        var modes = new ModeInfo[modeCount];
        if (QueryDisplayConfig(activeOnly, ref pathCount, paths, ref modeCount, modes, 0) != 0) return names;
        foreach (var path in paths.Take((int)pathCount))
        {
            var source = new SourceName { Header = new Header { Type = 1, Size = Marshal.SizeOf<SourceName>(),
                Adapter = path.SourceAdapter, Id = path.SourceId } };
            var target = new TargetName { Header = new Header { Type = 2, Size = Marshal.SizeOf<TargetName>(),
                Adapter = path.TargetAdapter, Id = path.TargetId } };
            if (GetSourceName(ref source) == 0 && GetTargetName(ref target) == 0 && target.Friendly.Length > 0)
                names[source.Device] = target.Friendly;
        }
        return names;
    }

    // --- Recycle Bin ---
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    struct FileOperation
    {
        public nint Window;
        public uint Func;
        public string From;
        public string? To;
        public ushort Flags;
        [MarshalAs(UnmanagedType.Bool)] public bool Aborted;
        public nint Mappings;
        public string? Title;
    }

    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    static extern int SHFileOperation(ref FileOperation operation);

    /// <summary>Move a file to the Recycle Bin, without any dialog.</summary>
    public static bool Recycle(string path)
    {
        const uint delete = 3;
        const ushort allowUndo = 0x40, noConfirmation = 0x10, silent = 0x4, noErrorUi = 0x400;
        var op = new FileOperation { Func = delete, From = path + "\0\0",
                                     Flags = allowUndo | noConfirmation | silent | noErrorUi };
        return SHFileOperation(ref op) == 0 && !op.Aborted;
    }
}
