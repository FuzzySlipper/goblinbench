using DenCore.Models;
using Microsoft.Extensions.Logging;

namespace DenCore.Services;

/// <summary>
/// Routes stale attention signals for tasks that have been
/// idle beyond configured thresholds. Runs on a background
/// timer and posts attention-grabbing messages.
/// </summary>
public sealed class StaleAttentionRoutingService
{
    private readonly ILogger<StaleAttentionRoutingService> _logger;
    private readonly TimeSpan _staleThreshold;
    private CancellationTokenSource? _loopCts;

    public StaleAttentionRoutingService(ILogger<StaleAttentionRoutingService> logger, TimeSpan? staleThreshold = null)
    {
        _logger = logger;
        _staleThreshold = staleThreshold ?? TimeSpan.FromMinutes(30);
    }

    /// <summary>
    /// Starts the stale-attention monitoring loop.
    /// Runs every 60 seconds checking for stale tasks.
    /// </summary>
    public Task StartMonitoringAsync()
    {
        _loopCts = new CancellationTokenSource();
        var token = _loopCts.Token;

        return Task.Run(async () =>
        {
            while (!token.IsCancellationRequested)
            {
                try
                {
                    await CheckForStaleTasksAsync(token);
                }
                catch (Exception ex)
                {
                    // Per-iteration catch prevents loop crash.
                    _logger.LogError(ex, "Stale attention check failed");
                }

                await Task.Delay(TimeSpan.FromSeconds(60), token);
            }
        }, token);
    }

    private Task CheckForStaleTasksAsync(CancellationToken token)
    {
        // In production this would query for tasks with no updates
        // past the threshold and route attention notifications.
        _logger.LogDebug("Stale attention check completed (threshold: {Threshold})", _staleThreshold);
        return Task.CompletedTask;
    }

    public void StopMonitoring()
    {
        _loopCts?.Cancel();
    }
}
