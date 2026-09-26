// Design kit for digital products. This file is copied into the render sandbox as
// kit.tsx, so agent scripts compose these components instead of styling from scratch.
// Fonts resolve from @expo-google-fonts packages (static TTFs) installed in the sandbox (see tools.ts).
import type { ReactNode } from "react";
import { Document, Page, View, Text, Image, Link, StyleSheet, Font } from "@react-pdf/renderer";

const fontFile = (pkg: string, weight: string, family: string) => `node_modules/@expo-google-fonts/${pkg}/${weight}/${family}_${weight}.ttf`;

Font.register({
    family: "Inter",
    fonts: [
        { src: fontFile("inter", "400Regular", "Inter"), fontWeight: 400 },
        { src: fontFile("inter", "400Regular_Italic", "Inter"), fontWeight: 400, fontStyle: "italic" },
        { src: fontFile("inter", "600SemiBold", "Inter"), fontWeight: 600 },
        { src: fontFile("inter", "700Bold", "Inter"), fontWeight: 700 },
        { src: fontFile("inter", "800ExtraBold", "Inter"), fontWeight: 800 },
    ],
});
Font.register({
    family: "JetBrains Mono",
    fonts: [
        { src: fontFile("jetbrains-mono", "400Regular", "JetBrainsMono"), fontWeight: 400 },
        { src: fontFile("jetbrains-mono", "700Bold", "JetBrainsMono"), fontWeight: 700 },
    ],
});
// Keep words whole — react-pdf's default hyphenation splits them mid-word.
Font.registerHyphenationCallback((word) => [word]);

export const theme = {
    color: {
        ink: "#0B1220",
        inkSoft: "#1E293B",
        text: "#1F2937",
        muted: "#64748B",
        rule: "#E2E8F0",
        paper: "#FFFFFF",
        panel: "#F8FAFC",
        accent: "#6366F1",
        accentSoft: "#EEF2FF",
        tip: "#059669",
        tipSoft: "#ECFDF5",
        warning: "#D97706",
        warningSoft: "#FFFBEB",
        onDark: "#F8FAFC",
        onDarkMuted: "#94A3B8",
    },
    font: { body: "Inter", mono: "JetBrains Mono" },
    size: { eyebrow: 9, small: 9, body: 10.5, lead: 13, h2: 15, h1: 24, display: 38 },
    space: { page: 56, block: 14 },
};
const c = theme.color;
// JetBrains Mono's coding ligatures (e.g. "</") crash fontkit's glyph metrics, so mono text renders without them.
const noLigatures = { fontFeatureSettings: { calt: false, liga: false } } as {};

const s = StyleSheet.create({
    page: { fontFamily: "Inter", fontSize: theme.size.body, color: c.text, lineHeight: 1.55, backgroundColor: c.paper, paddingTop: 72, paddingBottom: 64, paddingHorizontal: theme.space.page },
    darkPage: { fontFamily: "Inter", backgroundColor: c.ink, color: c.onDark, padding: theme.space.page },
    header: { position: "absolute", top: 28, left: theme.space.page, right: theme.space.page, flexDirection: "row", justifyContent: "space-between", fontSize: 8, color: c.muted, borderBottomWidth: 0.5, borderBottomColor: c.rule, paddingBottom: 6 },
    // react-pdf drops fixed elements positioned with `bottom` on wrapping pages, so pin from the top of A4 (842pt).
    footer: { position: "absolute", top: 842 - 40, left: theme.space.page, right: theme.space.page, flexDirection: "row", justifyContent: "space-between", fontSize: 8, color: c.muted },
    eyebrow: { fontSize: theme.size.eyebrow, fontWeight: 700, letterSpacing: 1.6, textTransform: "uppercase", color: c.accent },
    h1: { fontSize: theme.size.h1, fontWeight: 800, color: c.ink, lineHeight: 1.2, marginTop: 6 },
    h1Rule: { width: 48, height: 3, backgroundColor: c.accent, marginTop: 10, marginBottom: 18 },
    h2: { fontSize: theme.size.h2, fontWeight: 700, color: c.ink, marginTop: 18, marginBottom: 6 },
    p: { marginBottom: 10 },
    lead: { fontSize: theme.size.lead, color: c.inkSoft, lineHeight: 1.5, marginBottom: 14 },
    bulletRow: { flexDirection: "row", marginBottom: 5 },
    bulletDot: { width: 5, height: 5, borderRadius: 3, backgroundColor: c.accent, marginTop: 6, marginRight: 9 },
    card: { borderRadius: 6, padding: 14, marginVertical: 10, borderLeftWidth: 3 },
    cardTitle: { fontSize: 10, fontWeight: 700, marginBottom: 4, textTransform: "uppercase", letterSpacing: 0.8 },
    code: { ...noLigatures, fontFamily: "JetBrains Mono", fontSize: 8.8, lineHeight: 1.5, backgroundColor: c.ink, color: c.onDark, borderRadius: 6, padding: 14, marginVertical: 10 },
    codeLabel: { ...noLigatures, fontFamily: "JetBrains Mono", fontSize: 7.5, color: c.onDarkMuted, marginBottom: 6, textTransform: "uppercase", letterSpacing: 1 },
    statsRow: { flexDirection: "row", marginVertical: 12 },
    stat: { flex: 1, backgroundColor: c.panel, borderRadius: 6, padding: 12, marginRight: 8 },
    statValue: { fontSize: 22, fontWeight: 800, color: c.accent, lineHeight: 1.2 },
    statLabel: { fontSize: 8.5, color: c.muted, marginTop: 2 },
    figure: { marginVertical: 12 },
    figureImg: { width: "100%", borderRadius: 6 },
    caption: { fontSize: 8.5, color: c.muted, marginTop: 6, fontStyle: "italic" },
    checkRow: { flexDirection: "row", alignItems: "flex-start", paddingVertical: 9, borderBottomWidth: 0.5, borderBottomColor: c.rule },
    checkBox: { width: 13, height: 13, borderWidth: 1.4, borderColor: c.accent, borderRadius: 3, marginRight: 12, marginTop: 1 },
    checkTitle: { fontWeight: 600, color: c.ink },
    checkDetail: { fontSize: 9, color: c.muted, marginTop: 2 },
});

// ---------- Document shell ----------

export function KitDocument({ title, author, children }: { title: string; author?: string | undefined; children: ReactNode }) {
    return <Document title={title} {...(author ? { author, creator: author, producer: author } : {})}>{children}</Document>;
}

// ---------- Full-page layouts ----------

export function CoverPage({ eyebrow, title, subtitle, author, edition, imageUrl }: {
    eyebrow?: string | undefined; title: string; subtitle?: string | undefined; author?: string | undefined; edition?: string | undefined; imageUrl?: string | undefined;
}) {
    return (
        <Page size="A4" style={s.darkPage}>
            <View style={{ flexDirection: "row", justifyContent: "space-between" }}>
                <Text style={{ fontSize: 9, fontWeight: 700, letterSpacing: 1.6, color: c.onDarkMuted, textTransform: "uppercase" }}>{author ?? ""}</Text>
                <Text style={{ fontSize: 9, color: c.onDarkMuted }}>{edition ?? ""}</Text>
            </View>
            {imageUrl
                ? <Image src={imageUrl} style={{ width: "100%", height: 250, objectFit: "cover", borderRadius: 8, marginTop: 40 }} />
                : <View style={{ height: 120 }} />}
            <View style={{ marginTop: "auto" }}>
                {eyebrow && <Text style={[s.eyebrow, { color: c.accent, marginBottom: 12 }]}>{eyebrow}</Text>}
                <Text style={{ fontSize: theme.size.display, fontWeight: 800, lineHeight: 1.1, color: c.onDark }}>{title}</Text>
                <View style={[s.h1Rule, { width: 72, marginTop: 20 }]} />
                {subtitle && <Text style={{ fontSize: 14, color: c.onDarkMuted, lineHeight: 1.5, maxWidth: 420 }}>{subtitle}</Text>}
            </View>
        </Page>
    );
}

/** A flowing content page with running header/footer; content wraps onto new pages automatically. */
export function ContentPage({ docTitle, brand, children }: { docTitle: string; brand?: string | undefined; children: ReactNode }) {
    return (
        <Page size="A4" style={s.page} wrap>
            <View style={s.header} fixed>
                <Text>{brand ?? ""}</Text>
                <Text>{docTitle}</Text>
            </View>
            <View style={s.footer} fixed>
                <Text>{docTitle}</Text>
                <Text render={({ pageNumber, totalPages }) => `${pageNumber} / ${totalPages}`} />
            </View>
            {children}
        </Page>
    );
}

export function ChecklistPage({ docTitle, brand, title, intro, items }: {
    docTitle: string; brand?: string | undefined; title: string; intro?: string | undefined; items: { title: string; detail?: string | undefined }[];
}) {
    return (
        <ContentPage docTitle={docTitle} brand={brand}>
            <SectionHeader eyebrow="Checklist" title={title} />
            {intro && <Lead>{intro}</Lead>}
            {items.map((item, i) => (
                <View key={i} style={s.checkRow} wrap={false}>
                    <View style={s.checkBox} />
                    <View style={{ flex: 1 }}>
                        <Text style={s.checkTitle}>{item.title}</Text>
                        {item.detail && <Text style={s.checkDetail}>{item.detail}</Text>}
                    </View>
                </View>
            ))}
        </ContentPage>
    );
}

export function CTAPage({ eyebrow, heading, body, buttonLabel, url, footnote }: {
    eyebrow?: string | undefined; heading: string; body: string; buttonLabel: string; url: string; footnote?: string | undefined;
}) {
    return (
        <Page size="A4" style={[s.darkPage, { justifyContent: "center" }]}>
            {eyebrow && <Text style={[s.eyebrow, { marginBottom: 14 }]}>{eyebrow}</Text>}
            <Text style={{ fontSize: 30, fontWeight: 800, lineHeight: 1.15 }}>{heading}</Text>
            <View style={[s.h1Rule, { marginTop: 18 }]} />
            <Text style={{ fontSize: 13, color: c.onDarkMuted, lineHeight: 1.6, maxWidth: 420, marginBottom: 28 }}>{body}</Text>
            <Link src={url} style={{ textDecoration: "none", alignSelf: "flex-start" }}>
                <Text style={{ backgroundColor: c.accent, color: c.onDark, fontWeight: 700, fontSize: 12, paddingVertical: 12, paddingHorizontal: 22, borderRadius: 6 }}>{buttonLabel}  →</Text>
            </Link>
            <Text style={{ fontSize: 9, color: c.onDarkMuted, marginTop: 14 }}>{footnote ?? url}</Text>
        </Page>
    );
}

// ---------- Blocks (use inside ContentPage) ----------

/** Starts a major section. Pass breakBefore to force it onto a new page. */
export function SectionHeader({ eyebrow, title, breakBefore }: { eyebrow?: string | undefined; title: string; breakBefore?: boolean | undefined }) {
    return (
        <View break={breakBefore ?? false} minPresenceAhead={80}>
            {eyebrow && <Text style={s.eyebrow}>{eyebrow}</Text>}
            <Text style={s.h1}>{title}</Text>
            <View style={s.h1Rule} />
        </View>
    );
}

export const H2 = ({ children }: { children: ReactNode }) => <Text style={s.h2} minPresenceAhead={40}>{children}</Text>;
export const P = ({ children }: { children: ReactNode }) => <Text style={s.p}>{children}</Text>;
export const Lead = ({ children }: { children: ReactNode }) => <Text style={s.lead}>{children}</Text>;
export const Strong = ({ children }: { children: ReactNode }) => <Text style={{ fontWeight: 700, color: c.ink }}>{children}</Text>;

export function Bullets({ items }: { items: ReactNode[] }) {
    return (
        <View style={{ marginBottom: 10 }}>
            {items.map((item, i) => (
                <View key={i} style={s.bulletRow} wrap={false}>
                    <View style={s.bulletDot} />
                    <Text style={{ flex: 1 }}>{item}</Text>
                </View>
            ))}
        </View>
    );
}

const tones = {
    note: { border: c.accent, bg: c.accentSoft },
    tip: { border: c.tip, bg: c.tipSoft },
    warning: { border: c.warning, bg: c.warningSoft },
};

export function Callout({ tone = "note", title, children }: { tone?: keyof typeof tones | undefined; title?: string | undefined; children: ReactNode }) {
    const t = tones[tone];
    return (
        <View style={[s.card, { borderLeftColor: t.border, backgroundColor: t.bg }]} wrap={false}>
            {title && <Text style={[s.cardTitle, { color: t.border }]}>{title}</Text>}
            <Text style={{ color: c.inkSoft }}>{children}</Text>
        </View>
    );
}

/** Monospace block for prompts, templates, or code. */
export function ExampleBlock({ label, children }: { label?: string | undefined; children: string }) {
    return (
        <View style={s.code} wrap={false}>
            {label && <Text style={s.codeLabel}>{label}</Text>}
            <Text>{children}</Text>
        </View>
    );
}

export function StatRow({ stats }: { stats: { value: string; label: string }[] }) {
    return (
        <View style={s.statsRow} wrap={false}>
            {stats.map((st, i) => (
                <View key={i} style={[s.stat, i === stats.length - 1 ? { marginRight: 0 } : {}]}>
                    <Text style={s.statValue}>{st.value}</Text>
                    <Text style={s.statLabel}>{st.label}</Text>
                </View>
            ))}
        </View>
    );
}

export function Figure({ src, caption, height }: { src: string; caption?: string | undefined; height?: number | undefined }) {
    return (
        <View style={s.figure} wrap={false}>
            <Image src={src} style={[s.figureImg, height ? { height, objectFit: "cover" } : {}]} />
            {caption && <Text style={s.caption}>{caption}</Text>}
        </View>
    );
}

/** Numbered steps, e.g. a workflow. */
export function Steps({ steps }: { steps: { title: string; body: string }[] }) {
    return (
        <View style={{ marginVertical: 8 }}>
            {steps.map((st, i) => (
                <View key={i} style={{ flexDirection: "row", marginBottom: 12 }} wrap={false}>
                    <Text style={{ width: 26, height: 26, borderRadius: 13, backgroundColor: c.ink, color: c.onDark, fontWeight: 700, fontSize: 10, textAlign: "center", paddingTop: 6, marginRight: 12 }}>{i + 1}</Text>
                    <View style={{ flex: 1 }}>
                        <Text style={{ fontWeight: 700, color: c.ink }}>{st.title}</Text>
                        <Text style={{ color: c.text }}>{st.body}</Text>
                    </View>
                </View>
            ))}
        </View>
    );
}
