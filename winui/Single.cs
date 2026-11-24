using Microsoft.Windows.AppLifecycle;

namespace Laiaudio;

/// <summary>One Laiaudio at a time: opening it again brings the running window to the front.</summary>
static class Single
{
    public static event Action? Activated;

    public static bool AlreadyRunning()
    {
        var main = AppInstance.FindOrRegisterForKey("main");
        if (!main.IsCurrent)
        {
            var args = AppInstance.GetCurrent().GetActivatedEventArgs();
            Task.Run(() => main.RedirectActivationToAsync(args).AsTask()).Wait();
            return true;
        }
        main.Activated += (_, _) => Activated?.Invoke();
        return false;
    }
}
