import { useState, useEffect, useCallback } from 'react';
import { Cpu, RotateCcw, ChevronDown, ChevronUp } from 'lucide-react';
import { getGpuStats, resetGpuPeak } from '../api';

function UsageBar({ value, max, peak, label, color }) {
    const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
    const peakPct = max > 0 ? Math.min((peak / max) * 100, 100) : 0;

    return (
        <div className="flex flex-col gap-1">
            <div className="flex justify-between text-[11px] text-neutral-400">
                <span>{label}</span>
                <span>{value.toFixed(0)} / {max.toFixed(0)} MB</span>
            </div>
            <div className="relative w-full h-2 bg-neutral-700 rounded-full overflow-hidden">
                <div
                    className="absolute inset-y-0 left-0 rounded-full transition-all duration-500"
                    style={{ width: `${pct}%`, backgroundColor: color }}
                />
                {peak > value && (
                    <div
                        className="absolute top-0 bottom-0 w-[2px] transition-all duration-500"
                        style={{ left: `${peakPct}%`, backgroundColor: '#ef4444' }}
                        title={`Peak: ${peak.toFixed(0)} MB`}
                    />
                )}
            </div>
        </div>
    );
}

function getBarColor(pct) {
    if (pct < 50) return '#22c55e';
    if (pct < 75) return '#eab308';
    if (pct < 90) return '#f97316';
    return '#ef4444';
}

export default function GpuMonitor() {
    const [data, setData] = useState(null);
    const [expanded, setExpanded] = useState(false);
    const [error, setError] = useState(false);

    const fetchStats = useCallback(async () => {
        try {
            const stats = await getGpuStats();
            setData(stats);
            setError(false);
        } catch {
            setError(true);
        }
    }, []);

    useEffect(() => {
        fetchStats();
        const interval = setInterval(fetchStats, 2000);
        return () => clearInterval(interval);
    }, [fetchStats]);

    const handleResetPeak = async (e) => {
        e.stopPropagation();
        try {
            await resetGpuPeak();
            await fetchStats();
        } catch { /* ignore */ }
    };

    if (error || !data || !data.available) {
        return (
            <div className="mx-3 mb-3 px-3 py-2 bg-neutral-800/50 rounded-lg">
                <div className="flex items-center gap-2 text-neutral-500 text-xs">
                    <Cpu size={14} />
                    <span>GPU: N/A</span>
                </div>
            </div>
        );
    }

    const gpu = data.gpus[0];
    if (!gpu) return null;

    const usagePct = gpu.usage_pct;
    const barColor = getBarColor(usagePct);
    const limitOk = gpu.within_8gb_limit;

    return (
        <div className="mx-3 mb-3">
            <button
                onClick={() => setExpanded(!expanded)}
                className="flex items-center gap-2 w-full px-3 py-2
                    bg-neutral-800/60 hover:bg-neutral-800 rounded-lg
                    transition cursor-pointer text-left"
            >
                <Cpu size={14} className="text-neutral-400 shrink-0" />
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                        <span className="text-xs text-neutral-300 truncate">
                            VRAM {gpu.memory_used_gb} / {gpu.memory_total_gb} GB
                        </span>
                        <span
                            className="text-[10px] font-mono px-1.5 py-0.5 rounded"
                            style={{
                                backgroundColor: limitOk ? '#22c55e20' : '#ef444420',
                                color: limitOk ? '#22c55e' : '#ef4444',
                            }}
                        >
                            {limitOk ? 'OK' : 'OVER'}
                        </span>
                    </div>
                    <div className="w-full h-1 bg-neutral-700 rounded-full mt-1 overflow-hidden">
                        <div
                            className="h-full rounded-full transition-all duration-500"
                            style={{ width: `${usagePct}%`, backgroundColor: barColor }}
                        />
                    </div>
                </div>
                {expanded
                    ? <ChevronDown size={12} className="text-neutral-500 shrink-0" />
                    : <ChevronUp size={12} className="text-neutral-500 shrink-0" />}
            </button>

            {expanded && (
                <div className="mt-1 px-3 py-3 bg-neutral-800/40 rounded-lg space-y-3">
                    <div className="flex items-center justify-between">
                        <span className="text-[11px] text-neutral-400 truncate" title={gpu.name}>
                            {gpu.name}
                        </span>
                        <button
                            onClick={handleResetPeak}
                            className="flex items-center gap-1 text-[10px] text-neutral-500
                                hover:text-neutral-300 transition cursor-pointer"
                            title="Reset peak counter"
                        >
                            <RotateCcw size={10} />
                            Reset peak
                        </button>
                    </div>

                    <UsageBar
                        value={gpu.memory_used_mb}
                        max={gpu.memory_total_mb}
                        peak={gpu.peak_memory_mb}
                        label="VRAM"
                        color={barColor}
                    />

                    <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
                        <div className="text-neutral-500">Current</div>
                        <div className="text-neutral-300 text-right">{gpu.memory_used_mb.toFixed(0)} MB</div>

                        <div className="text-neutral-500">Peak</div>
                        <div className="text-right" style={{ color: limitOk ? '#22c55e' : '#ef4444' }}>
                            {gpu.peak_memory_mb.toFixed(0)} MB ({gpu.peak_memory_gb} GB)
                        </div>

                        <div className="text-neutral-500">GPU Load</div>
                        <div className="text-neutral-300 text-right">{gpu.utilization_pct}%</div>

                        <div className="text-neutral-500">Temp</div>
                        <div className="text-neutral-300 text-right">{gpu.temperature_c}°C</div>

                        <div className="text-neutral-500">8 GB Limit</div>
                        <div className="text-right font-mono" style={{ color: limitOk ? '#22c55e' : '#ef4444' }}>
                            {limitOk ? 'PASS' : 'FAIL'}
                        </div>
                    </div>

                    {data.gpus.length > 1 && (
                        <div className="border-t border-neutral-700 pt-2 space-y-2">
                            {data.gpus.slice(1).map((g) => (
                                <div key={g.gpu_id} className="text-[11px]">
                                    <div className="text-neutral-500 mb-1">GPU {g.gpu_id}: {g.name}</div>
                                    <UsageBar
                                        value={g.memory_used_mb}
                                        max={g.memory_total_mb}
                                        peak={g.peak_memory_mb}
                                        label=""
                                        color={getBarColor(g.usage_pct)}
                                    />
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
