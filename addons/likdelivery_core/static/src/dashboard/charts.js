/** @odoo-module */

import { Component, useState } from "@odoo/owl";

/**
 * Primitives graphiques du tableau de bord Livraison.
 *
 * SVG pur, aucune dépendance : les mêmes tracés que LikDelivery-Web
 * (src/components/ui/chart.tsx). Les couleurs sont posées en attributs de
 * présentation — un var() placé dans un attribut SVG n'est pas résolu partout
 * — et la palette est celle du thème clair de la PWA, socle du back-office.
 */

const TONES = {
    accent: "#2563EB",
    accent2: "#1D4ED8",
    success: "#16A34A",
    warning: "#F59E0B",
    danger: "#DC2626",
    purple: "#7C3AED",
    orange: "#EA580C",
    ink: "#334155",
    muted: "#94A3B8",
};

const HEIGHT = 240;
const WIDTH = 100;
const PAD = { top: 16, bottom: 24, left: 14, right: 4 };

let sequence = 0;

function toneColor(tone) {
    return TONES[tone] || TONES.accent;
}

/** 1 250 000 -> « 1,3 M », 12 400 -> « 12,4 k » : axes et légendes seulement. */
export function compact(value) {
    const abs = Math.abs(value);
    const format = (n, suffix) => `${n.toFixed(n < 10 ? 1 : 0).replace(".", ",")}${suffix}`;
    if (abs >= 1000000) {
        return format(value / 1000000, " M");
    }
    if (abs >= 1000) {
        return format(value / 1000, " k");
    }
    return String(Math.round(value));
}

function toPoints(values, max, height, top, bottom) {
    const innerH = height - top - bottom;
    const stepX = (WIDTH - PAD.left - PAD.right) / Math.max(1, values.length - 1);
    return values.map((value, index) => [
        PAD.left + index * stepX,
        top + innerH - (value / (max || 1)) * innerH,
    ]);
}

function toPath(points) {
    return points.map(([x, y], i) => `${i ? "L" : "M"} ${x.toFixed(2)} ${y.toFixed(2)}`).join(" ");
}

/* ============================================================
   Sparkline — tendance de pied de carte KPI.
   ============================================================ */
export class LikSparkline extends Component {
    static template = "likdelivery_core.Sparkline";
    static props = { data: Array, tone: { type: String, optional: true } };

    setup() {
        this.gradientId = `lik-spark-${++sequence}`;
    }

    get geometry() {
        const data = this.props.data;
        if (data.length < 2) {
            return null;
        }
        const max = Math.max(...data);
        const min = Math.min(...data);
        const span = max - min || 1;
        const stepX = 100 / (data.length - 1);
        const points = data.map((value, index) => [index * stepX, 30 - ((value - min) / span) * 28]);
        const path = toPath(points);
        return {
            path,
            area: `${path} L 100 32 L 0 32 Z`,
            stroke: toneColor(this.props.tone || "accent"),
            last: points[points.length - 1],
        };
    }
}

/* ============================================================
   Aire multi-séries — le « flux de trésorerie » de la maquette.
   ============================================================ */
export class LikAreaChart extends Component {
    static template = "likdelivery_core.AreaChart";
    static props = { chart: Object };

    setup() {
        this.gradientPrefix = `lik-area-${++sequence}`;
        this.state = useState({ hover: null });
    }

    get length() {
        return Math.max(...this.props.chart.series.map((serie) => serie.values.length), 0);
    }

    get max() {
        return Math.max(...this.props.chart.series.flatMap((serie) => serie.values), 1);
    }

    get series() {
        const max = this.max;
        return this.props.chart.series.map((serie, index) => {
            const color = toneColor(serie.color);
            const points = toPoints(serie.values, max, HEIGHT, PAD.top, PAD.bottom);
            const path = toPath(points);
            const floor = HEIGHT - PAD.bottom;
            return {
                index,
                name: serie.name,
                color,
                values: serie.values,
                total: compact(serie.values.reduce((a, b) => a + b, 0)),
                path,
                area: `${path} L ${points[this.length - 1][0].toFixed(2)} ${floor} L ${points[0][0].toFixed(2)} ${floor} Z`,
                points,
            };
        });
    }

    get grid() {
        const innerH = HEIGHT - PAD.top - PAD.bottom;
        return [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
            const y = PAD.top + innerH * (1 - ratio);
            return { y, top: `${(y / HEIGHT) * 100}%`, label: compact(this.max * ratio) };
        });
    }

    get columns() {
        return Array.from({ length: this.length }, (_, index) => index);
    }

    get marks() {
        if (this.state.hover === null) {
            return [];
        }
        return this.series.map((serie) => {
            const [x, y] = serie.points[this.state.hover] || [0, 0];
            return {
                index: serie.index,
                x: `${(x / WIDTH) * 100}%`,
                y: `${(y / HEIGHT) * 100}%`,
                color: serie.color,
            };
        });
    }

    get ticks() {
        const labels = this.props.chart.labels;
        const every = Math.ceil(labels.length / 7);
        const stepX = (WIDTH - PAD.left - PAD.right) / Math.max(1, labels.length - 1);
        return labels
            .map((label, index) => ({ label, index }))
            .filter(({ index }) => index % every === 0 || index === labels.length - 1)
            .map(({ label, index }) => ({
                label,
                x: `${((PAD.left + index * stepX) / WIDTH) * 100}%`,
            }));
    }

    get tooltip() {
        const hover = this.state.hover;
        if (hover === null) {
            return null;
        }
        const stepX = (WIDTH - PAD.left - PAD.right) / Math.max(1, this.length - 1);
        return {
            label: this.props.chart.labels[hover],
            left: `${Math.min(86, Math.max(14, ((PAD.left + hover * stepX) / WIDTH) * 100))}%`,
            rows: this.series.map((serie) => ({
                index: serie.index,
                name: serie.name,
                color: serie.color,
                value: compact(serie.values[hover] || 0),
            })),
        };
    }

    setHover(index) {
        this.state.hover = index;
    }

    clear() {
        this.state.hover = null;
    }
}

/* ============================================================
   Anneau de répartition, légende en pourcentages.
   ============================================================ */
export class LikDonut extends Component {
    static template = "likdelivery_core.Donut";
    static props = { chart: Object };

    get geometry() {
        const size = 150;
        const thickness = 15;
        const radius = (size - thickness) / 2;
        const circumference = 2 * Math.PI * radius;
        const total = this.props.chart.data.reduce((a, b) => a + b.value, 0) || 1;
        let offset = 0;
        return {
            size,
            thickness,
            radius,
            center: size / 2,
            total,
            slices: this.props.chart.data.map((slice) => {
                const length = (slice.value / total) * circumference;
                const segment = {
                    label: slice.label,
                    pct: slice.pct,
                    text: compact(slice.value),
                    color: toneColor(slice.color),
                    dasharray: `${length.toFixed(2)} ${(circumference - length).toFixed(2)}`,
                    dashoffset: -offset,
                };
                offset += length;
                return segment;
            }),
        };
    }
}

/* ============================================================
   Barres d'allocation — part du chiffre d'affaires.
   ============================================================ */
export class LikAllocation extends Component {
    static template = "likdelivery_core.Allocation";
    static props = { chart: Object };

    get items() {
        return this.props.chart.items.map((item) => ({
            label: item.label,
            text: item.text,
            pct: item.pct,
            width: `${Math.max(2, Math.min(100, item.pct))}%`,
            color: toneColor(item.color),
        }));
    }
}

/* ============================================================
   Barres appariées — encaissé contre en attente.
   ============================================================ */
export class LikPairs extends Component {
    static template = "likdelivery_core.Pairs";
    static props = { chart: Object };

    get aName() {
        return this.props.chart.a_name;
    }

    get bName() {
        return this.props.chart.b_name;
    }

    get groups() {
        const max = Math.max(...this.props.chart.groups.flatMap((group) => [group.a, group.b]), 1);
        const height = (value) => `${value > 0 ? Math.max(2, (value / max) * 100) : 0}%`;
        return this.props.chart.groups.map((group) => ({
            label: group.label,
            a: height(group.a),
            b: height(group.b),
            aText: compact(group.a),
            bText: compact(group.b),
        }));
    }

    get legend() {
        return [
            { name: this.aName, color: toneColor("accent") },
            { name: this.bName, color: toneColor("warning") },
        ];
    }
}
