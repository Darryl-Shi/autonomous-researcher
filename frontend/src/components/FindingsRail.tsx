import { AgentState, AgentInsight } from "@/lib/useExperiment";
import { ChartSpec } from "@/lib/api";
import { formatDistanceToNow } from "date-fns";
import { cn } from "@/lib/utils";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { motion, AnimatePresence } from "framer-motion";

type InsightWithAgent = AgentInsight & { agentId: string; gpu?: string };

interface FindingsRailProps {
    agents: Record<string, AgentState>;
}

function MiniChart({ chart }: { chart: ChartSpec }) {
    const width = 260;
    const height = 140; // slightly taller to fit axis labels
    const padding = { top: 14, right: 10, bottom: 28, left: 46 };

    const series = chart.series?.[0];
    if (!series || !Array.isArray(series.values) || series.values.length === 0) return null;

    const values = series.values.map((v) => Number(v)).filter((v) => Number.isFinite(v));
    if (values.length === 0) return null;

    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;

    const innerWidth = width - padding.left - padding.right;
    const innerHeight = height - padding.top - padding.bottom;

    const formatNumber = (val: number) => {
        const abs = Math.abs(val);
        if (abs >= 1_000_000_000) return `${(val / 1_000_000_000).toFixed(1)}b`;
        if (abs >= 1_000_000) return `${(val / 1_000_000).toFixed(1)}m`;
        if (abs >= 1_000) return `${(val / 1_000).toFixed(1)}k`;
        if (abs >= 100) return val.toFixed(0);
        if (abs >= 1) return val.toFixed(2);
        return val.toPrecision(2);
    };

    const pts = values.map((v, idx) => {
        const x = padding.left + (idx / Math.max(values.length - 1, 1)) * innerWidth;
        const y = padding.top + (1 - (v - min) / span) * innerHeight;
        return `${x},${y}`;
    });

    // Respect labels if they match the series length; otherwise fall back to indices.
    const xLabels =
        Array.isArray(chart.labels) && chart.labels.length === values.length
            ? chart.labels
            : values.map((_, idx) => `${idx + 1}`);

    const xTicks = (() => {
        const maxTicks = 4; // keep tiny chart readable
        const step = Math.max(1, Math.ceil(xLabels.length / maxTicks));
        const ticks: { idx: number; label: string; x: number }[] = [];
        for (let i = 0; i < xLabels.length; i += step) {
            const x = padding.left + (i / Math.max(xLabels.length - 1, 1)) * innerWidth;
            ticks.push({ idx: i, label: xLabels[i], x });
        }
        // Always include the last label for clarity
        if (ticks[ticks.length - 1]?.idx !== xLabels.length - 1) {
            const i = xLabels.length - 1;
            const x = padding.left + (i / Math.max(xLabels.length - 1, 1)) * innerWidth;
            ticks.push({ idx: i, label: xLabels[i], x });
        }
        return ticks;
    })();

    const yTicks = [0, 0.5, 1].map((t) => ({
        value: min + span * t,
        y: padding.top + (1 - t) * innerHeight,
    }));

    const bars = chart.type === "bar";

    return (
        <div className="pt-3">
            <div className="text-[10px] uppercase tracking-[0.2em] text-[#5c5c63] mb-2 flex items-center justify-between">
                <span>{chart.title || "Signal"}</span>
                <span className="text-[9px] text-[#7c7c83]">{series.name || "metric"}</span>
            </div>
            <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-[140px] text-white/80">
                <defs>
                    <linearGradient id="spark" x1="0" x2="0" y1="0" y2="1">
                        <stop offset="0%" stopColor="rgba(255,255,255,0.08)" />
                        <stop offset="100%" stopColor="rgba(255,255,255,0.02)" />
                    </linearGradient>
                </defs>
                <rect x="0" y="0" width={width} height={height} fill="url(#spark)" rx="10" />

                {/* Grid + axes */}
                <g stroke="rgba(255,255,255,0.15)" strokeWidth="1">
                    {yTicks.map(({ y }, i) => (
                        <line key={`grid-${i}`} x1={padding.left} x2={width - padding.right} y1={y} y2={y} />
                    ))}
                    <line x1={padding.left} x2={padding.left} y1={padding.top} y2={height - padding.bottom} />
                    <line x1={padding.left} x2={width - padding.right} y1={height - padding.bottom} y2={height - padding.bottom} />
                </g>

                {/* Y-axis labels */}
                <g fill="rgba(255,255,255,0.65)" fontSize="9" textAnchor="end">
                    {yTicks.map(({ y, value }, i) => (
                        <text key={`ylabel-${i}`} x={padding.left - 6} y={y + 3}>
                            {formatNumber(value)}
                        </text>
                    ))}
                </g>

                {/* X-axis labels */}
                <g fill="rgba(255,255,255,0.65)" fontSize="9" textAnchor="middle">
                    {xTicks.map(({ x, label }, i) => (
                        <text key={`xlabel-${i}`} x={x} y={height - 8}>
                            {label}
                        </text>
                    ))}
                </g>

                {bars ? (
                    values.map((v, idx) => {
                        const barWidth = innerWidth / Math.max(values.length * 1.4, 1);
                        const x = padding.left + idx * (innerWidth / Math.max(values.length - 1, 1));
                        const y = padding.top + (1 - (v - min) / span) * innerHeight;
                        const h = height - padding.bottom - y;
                        return (
                            <rect
                                key={idx}
                                x={x - barWidth / 2}
                                y={y}
                                width={barWidth}
                                height={h}
                                rx={2}
                                fill="rgba(255,255,255,0.45)"
                            />
                        );
                    })
                ) : (
                    <polyline
                        fill="none"
                        stroke="white"
                        strokeWidth="2"
                        points={pts.join(" ")}
                        strokeLinejoin="round"
                        strokeLinecap="round"
                    />
                )}
            </svg>
        </div>
    );
}

export function FindingsRail({ agents }: FindingsRailProps) {
    const insights: InsightWithAgent[] = Object.values(agents)
        .flatMap((agent) => (agent.insights || []).map((insight) => ({ ...insight, agentId: agent.id, gpu: agent.gpu })))
        .sort((a, b) => b.timestamp - a.timestamp)
        .slice(0, 24); // Cap to avoid ever-growing rail

    return (
        <AnimatePresence>
            {insights.length > 0 && (
                <motion.aside
                    initial={{ opacity: 0, x: 24 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: 24 }}
                    transition={{ duration: 0.35, ease: "easeOut" }}
                    className="hidden xl:flex w-[340px] shrink-0 h-screen bg-gradient-to-b from-[#0c0c0e] via-[#0a0a0a] to-[#060607] border-l border-white/5 relative overflow-hidden"
                >
                    <div className="absolute inset-0 opacity-40 pointer-events-none" style={{ background: "radial-gradient(circle at 80% 15%, #1f1f28 0, transparent 45%)" }} />
                    <div className="flex-1 overflow-y-auto custom-scrollbar pt-10 pb-14 px-6 space-y-5">
                        <div className="px-1 space-y-1">
                            <p className="text-[11px] font-semibold tracking-[0.25em] text-white/80 uppercase">Findings</p>
                            <p className="text-[12px] text-[#7c7c83] leading-relaxed">Live distillations of sub-agents—posted whenever they think.</p>
                        </div>

                        <div className="space-y-4">
                            {insights.map((insight) => (
                                <div
                                    key={insight.id}
                                    className={cn(
                                        "p-5 rounded-2xl border border-white/8 bg-white/5 backdrop-blur-xl shadow-[0_20px_60px_rgba(0,0,0,0.35)]",
                                        "hover:border-white/25 transition-all duration-300 hover:-translate-y-0.5"
                                    )}
                                >
                                    <div className="flex items-center justify-between text-[10px] uppercase tracking-[0.2em] text-[#8a8a92]">
                                        <span className="text-white/90">Agent {insight.agentId}</span>
                                        <span className="text-[#6d6d74]">
                                            {formatDistanceToNow(new Date(insight.timestamp), { addSuffix: true })}
                                        </span>
                                    </div>
                                    <div className="mt-3 text-[11px] text-[#cfd0d4] leading-relaxed prose prose-invert prose-p:my-1 prose-li:my-0 prose-p:text-[#cfd0d4] prose-li:text-[#cfd0d4] prose-strong:text-white prose-code:text-white/80 max-w-none">
                                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                            {insight.summary}
                                        </ReactMarkdown>
                                    </div>
                                    {insight.chart && insight.chart.series?.length ? (
                                        <div className="mt-4">
                                            <MiniChart chart={insight.chart} />
                                        </div>
                                    ) : null}
                                </div>
                            ))}
                        </div>
                    </div>
                </motion.aside>
            )}
        </AnimatePresence>
    );
}
