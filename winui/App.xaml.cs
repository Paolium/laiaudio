using Microsoft.UI.Xaml;

namespace Laiaudio;

public partial class App : Application
{
    MainWindow? window;

    public App() => InitializeComponent();

    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        if (Single.AlreadyRunning())
        {
            Exit();
            return;
        }
        window = new MainWindow();
        window.Activate();
    }
}
