"use client";

import Link from "next/link";
import { useLiveExample, LiveInputs, LiveProfile, LiveValidation } from "./LiveExample";

// ---------------------------------------------------------------------------
// Ocean cross-section used as the hero image. Isotherms are generated once at
// module load (deterministic, so server and client markup match).
// ---------------------------------------------------------------------------
const W = 1200;
const H = 400;
const PROBE_X = 780;

const surfaceY = (x) => 44 + 3 * Math.sin(x / 46) + 2 * Math.sin(x / 19);

const isothermY = (base, amp, eddy, phase) => (x) =>
  base +
  amp * Math.sin(x / 190 + phase) +
  amp * 0.45 * Math.sin(x / 71 + phase * 2) +
  eddy * Math.exp(-(((x - PROBE_X) / 170) ** 2));

const ISOTHERMS = [
  { temp: 28, y: isothermY(78, 6, 16, 0.4), fill: "#F7B289", label: "#7C2D12" },
  { temp: 26, y: isothermY(112, 8, 30, 1.1), fill: "#FFF7ED", label: "#7C2D12" },
  { temp: 20, y: isothermY(160, 10, 24, 1.9), fill: "#9BDDE8", label: "#003E47" },
  { temp: 15, y: isothermY(208, 10, 15, 2.6), fill: "#00B1C9", label: "#00272D" },
  { temp: 10, y: isothermY(266, 8, 8, 3.2), fill: "#006686", label: "#FFFFFF" },
  { temp: 5, y: isothermY(334, 6, 3, 4.0), fill: "#003E47", label: "#FFFFFF" }
];

const xs = Array.from({ length: W / 20 + 1 }, (_, i) => i * 20);
const linePath = (fn) => xs.map((x, i) => `${i ? "L" : "M"}${x},${fn(x).toFixed(1)}`).join(" ");
const areaPath = (fn) => `${linePath(fn)} L${W},${H} L0,${H} Z`;

const USES = [
  {
    name: "Cyclone forecasting",
    what: "How much heat sits above the 26 °C line, and how deep it goes. That heat is the fuel a storm burns on its way to landfall.",
    example: "TCHP · D26",
    exampleNote: "heat above the 26 °C isotherm",
    tone: "text-rose-300"
  },
  {
    name: "Underwater sound",
    what: "Sound speed follows temperature. We compute the sonic layer depth, below which sound bends downward and leaves a shadow zone.",
    example: "SLD",
    exampleNote: "Mackenzie (1981) sound speed",
    tone: "text-purple-300"
  },
  {
    name: "Fisheries",
    what: "Upwelling lifts the thermocline toward the surface. We map how deep the 20 °C water sits, which can be combined with chlorophyll data to find fishing zones.",
    example: "D20",
    exampleNote: "20 °C isotherm depth, per cell",
    tone: "text-emerald-300"
  },
  {
    name: "Finding similar days",
    what: "Every cell is also summarised as a 128-number embedding, so you can ask which other places and days looked most alike.",
    example: "128-D",
    exampleNote: "cosine similarity search",
    tone: "text-cyan-300"
  }
];

export default function LandingPage() {
  const live = useLiveExample();
  return (
    <div className="min-h-screen bg-surface text-on-surface flex flex-col selection:bg-secondary-container selection:text-on-secondary-container">
      <header className="w-full">
        <div className="h-16 max-w-7xl mx-auto px-margin-mobile sm:px-margin-desktop flex items-center justify-between">
          <span className="flex items-center gap-2.5">
            <span className="w-8 h-8 rounded-xl bg-primary flex items-center justify-center">
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M2 15C5 12 8 18 12 15C16 12 19 18 22 15" stroke="#FFFFFF" strokeLinecap="round" strokeWidth="2.2"></path>
                <ellipse cx="12" cy="12" rx="9" ry="4.5" stroke="#00B1C9" strokeDasharray="2 2" strokeWidth="1.6" transform="rotate(-25 12 12)"></ellipse>
              </svg>
            </span>
            <span className="font-headline-sm text-headline-sm text-primary">OceanEmbed</span>
          </span>
          <Link href="/dashboard" className="text-body-md font-medium text-secondary hover:text-primary transition-colors">
            Dashboard
          </Link>
        </div>
      </header>

      <main className="flex-1">
        {/* Hero */}
        <section className="max-w-7xl mx-auto px-margin-mobile sm:px-margin-desktop pt-16 sm:pt-24 pb-12 sm:pb-16">
          <h1
            className="landing-rise max-w-[15ch] font-display font-semibold text-primary tracking-[-0.03em] [text-wrap:balance]"
            style={{ fontSize: "clamp(2.6rem, 4.2vw + 1rem, 5rem)", lineHeight: 1.02 }}
          >
            Satellites see the surface. We work out the rest.
          </h1>
          <div className="mt-8 flex flex-col md:flex-row md:items-end justify-between gap-8">
            <p className="landing-rise [animation-delay:120ms] max-w-[52ch] text-body-lg text-on-surface-variant [text-wrap:pretty]">
              OceanEmbed estimates the temperature of the Bay of Bengal and Arabian Sea from the surface down to
              1,000 metres, using nothing but what satellites measure each day.
            </p>
            <div className="landing-rise [animation-delay:200ms] flex items-center gap-6 shrink-0">
              <Link
                href="/dashboard"
                className="group inline-flex items-center gap-2 bg-primary hover:bg-secondary text-on-primary text-body-md font-medium pl-6 pr-5 py-3 rounded-xl transition-colors"
              >
                Open the dashboard
                <span className="material-symbols-outlined text-[20px] transition-transform duration-300 ease-out group-hover:translate-x-0.5">arrow_forward</span>
              </Link>
              <a href="#how" className="text-body-md font-medium text-secondary hover:text-primary transition-colors">
                How it works
              </a>
            </div>
          </div>
        </section>

        {/* Cross-section */}
        <figure className="relative">
          <svg
            viewBox={`0 0 ${W} ${H}`}
            preserveAspectRatio="xMidYMid slice"
            className="block w-full h-[320px] sm:h-auto"
            role="img"
            aria-label="Cross-section of the ocean. Warm water near the surface gives way to colder layers with depth; the layers dip under a warm eddy where the probe sits."
          >
            <path d={areaPath(surfaceY)} fill="#EA580C" />
            {ISOTHERMS.map((iso) => (
              <path key={iso.temp} d={areaPath(iso.y)} fill={iso.fill} />
            ))}
            {ISOTHERMS.map((iso, i) => (
              <path
                key={`line-${iso.temp}`}
                d={linePath(iso.y)}
                fill="none"
                stroke="#FFFFFF"
                strokeOpacity="0.55"
                strokeWidth="1"
                className="landing-draw" pathLength={1}
                style={{ animationDelay: `${200 + i * 90}ms` }}
              />
            ))}
            {ISOTHERMS.map((iso) => (
              <text key={`t-${iso.temp}`} x={PROBE_X - 12} y={iso.y(PROBE_X - 12) + 16} textAnchor="end" fontSize="12" fontWeight="600" fill={iso.label}>
                {iso.temp} °C
              </text>
            ))}

            {/* Probe: satellite overhead, dashed line down through the column */}
            <line x1={PROBE_X} x2={PROBE_X} y1="8" y2={H} stroke="#00253D" strokeWidth="1.2" strokeDasharray="3 4" />
            <rect x={PROBE_X - 7} y="2" width="14" height="9" rx="1.5" fill="#00253D" />
            <rect x={PROBE_X - 22} y="4.5" width="12" height="4" fill="#00B1C9" />
            <rect x={PROBE_X + 10} y="4.5" width="12" height="4" fill="#00B1C9" />
            <circle cx={PROBE_X} cy={surfaceY(PROBE_X)} r="4" fill="#00253D" stroke="#FFFFFF" strokeWidth="1.5" />
            <text x={PROBE_X - 12} y={surfaceY(PROBE_X) + 22} textAnchor="end" fontSize="12" fill="#FFFFFF" fontWeight="600">
              Schematic, not data
            </text>

            <text x="24" y={H - 16} fontSize="12" fill="#FFFFFF" fillOpacity="0.8">1,000 m</text>
          </svg>
          <figcaption className="sr-only">Schematic illustration of ocean layering; not model output.</figcaption>
        </figure>

        {/* How it works */}
        <section id="how" className="scroll-mt-8 bg-surface-container-lowest">
          <div className="max-w-7xl mx-auto px-margin-mobile sm:px-margin-desktop py-20 sm:py-28">
            <h2 className="max-w-[26ch] font-headline-lg text-headline-lg-mobile sm:text-headline-lg text-primary [text-wrap:balance]">
              Seven surface readings in. Fifteen depths out.
            </h2>

            <div className="mt-14 grid grid-cols-1 lg:grid-cols-12 gap-12 lg:gap-10 items-start">
              <div className="lg:col-span-5">
                <LiveInputs state={live} />
              </div>

              <div className="lg:col-span-3 flex flex-col gap-4 lg:pt-2">
                <span className="material-symbols-outlined text-[28px] text-on-tertiary-container hidden lg:inline-block" aria-hidden="true">
                  arrow_forward
                </span>
                <p className="text-body-lg text-on-surface [text-wrap:pretty]">
                  A convolutional network looks at a 0.25° patch around the point.
                </p>
                <p className="text-body-md text-on-surface-variant leading-relaxed [text-wrap:pretty]">
                  It was trained on GLORYS12 ocean reanalysis, so it has seen how surface patterns line up with what
                  happens underneath: warm eddies pushing heat down, upwelling pulling cold water up.
                </p>
              </div>

              <div className="lg:col-span-4 w-full max-w-sm lg:max-w-none">
                <LiveProfile state={live} />
              </div>
            </div>

            <p className="mt-20 sm:mt-28 max-w-[34ch] font-headline-md text-[26px] leading-[34px] sm:text-[32px] sm:leading-[42px] text-primary tracking-[-0.015em] [text-wrap:balance]">
              Trained on GLORYS12 reanalysis, checked against days it never saw. <LiveValidation state={live} />
            </p>
            <Link href="/dashboard#validation" className="mt-5 inline-flex items-center gap-1 text-body-md font-medium text-secondary hover:text-primary transition-colors">
              See the validation numbers
              <span className="material-symbols-outlined text-[18px]">arrow_forward</span>
            </Link>
          </div>
        </section>

        {/* Uses */}
        <section className="bg-primary-container text-on-primary">
          <div className="max-w-7xl mx-auto px-margin-mobile sm:px-margin-desktop py-20 sm:py-28">
            <h2 className="max-w-[22ch] font-headline-lg text-headline-lg-mobile sm:text-headline-lg [text-wrap:balance]">
              What a temperature profile is good for
            </h2>

            <ul className="mt-14 border-t border-white/15">
              {USES.map((use) => (
                <li key={use.name} className="grid grid-cols-1 md:grid-cols-12 gap-3 md:gap-8 py-8 border-b border-white/15">
                  <h3 className="md:col-span-3 font-headline-sm text-[20px] leading-[28px]">{use.name}</h3>
                  <p className="md:col-span-6 text-body-lg text-primary-fixed leading-relaxed [text-wrap:pretty]">{use.what}</p>
                  <div className="md:col-span-3 md:text-right">
                    <div className={`font-data-metric text-data-metric ${use.tone}`}>{use.example}</div>
                    <div className="text-body-sm text-primary-fixed-dim">{use.exampleNote}</div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* Close */}
        <section className="bg-primary text-on-primary">
          <div className="max-w-7xl mx-auto px-margin-mobile sm:px-margin-desktop pt-24 pb-16 sm:pt-32">
            <h2
              className="max-w-[16ch] font-display font-semibold tracking-[-0.03em] [text-wrap:balance]"
              style={{ fontSize: "clamp(2.2rem, 3vw + 1rem, 3.75rem)", lineHeight: 1.05 }}
            >
              Pick a point on the map. Go down.
            </h2>
            <Link
              href="/dashboard"
              className="group mt-10 inline-flex items-center gap-2 bg-surface-container-lowest hover:bg-secondary-fixed text-primary text-body-md font-medium pl-6 pr-5 py-3 rounded-xl transition-colors"
            >
              Open the dashboard
              <span className="material-symbols-outlined text-[20px] transition-transform duration-300 ease-out group-hover:translate-x-0.5">arrow_forward</span>
            </Link>

            <footer className="mt-24 pt-6 border-t border-white/10 flex flex-col sm:flex-row justify-between gap-2 text-body-sm text-primary-fixed-dim">
              <span>OceanEmbed · Team OceanSATX · Smart India Hackathon 2026, PS 26066</span>
              <span>Bay of Bengal &amp; Arabian Sea</span>
            </footer>
          </div>
        </section>
      </main>
    </div>
  );
}
