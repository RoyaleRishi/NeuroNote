import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Bricolage_Grotesque, Inter, JetBrains_Mono, Newsreader } from "next/font/google";
import "katex/dist/katex.min.css";
import "../styles/tokens.css";
import "./globals.css";
import { ToastProvider } from "../lib/toast";
import { ToastContainer } from "../components/ui/ToastContainer";
import { PreferencesProvider } from "../lib/preferences/PreferencesProvider";

/**
 * Type system mirrored from the owner's personal site (rsrikaanth.com):
 * - Bricolage Grotesque — characterful display face for headings/titles,
 *   set with tight negative tracking. Exposed as `--font-display-next`.
 * - Inter — body + UI chrome. Exposed as `--font-body-next`.
 * - JetBrains Mono — the signature uppercase, letter-spaced micro-labels
 *   (eyebrows, stat labels, metadata). Exposed as `--font-mono-next`.
 */
const display = Bricolage_Grotesque({
  subsets: ["latin"],
  weight: ["600", "700", "800"],
  variable: "--font-display-next",
  display: "swap",
});

const bodyFont = Inter({
  subsets: ["latin"],
  variable: "--font-body-next",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono-next",
  display: "swap",
});

/**
 * Newsreader serif is retained only for optional emphasis inside the note
 * body. Exposed as the `--font-serif-next` CSS variable.
 */
const serif = Newsreader({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  style: ["normal", "italic"],
  variable: "--font-serif-next",
  display: "swap",
  // Newsreader has no entry in Next's font-metrics table, which logs a noisy
  // "Failed to find font override values" warning. Skip the synthetic fallback
  // adjustment; `display: swap` already handles the load gracefully.
  adjustFontFallback: false,
});

export const metadata: Metadata = {
  title: {
    default: "NeuroNote",
    template: "%s | NeuroNote",
  },
  description:
    "Knowledge graph note-taking application with bidirectional linking and entity extraction",
  keywords: ["notes", "knowledge graph", "PKM", "bidirectional links", "entities", "note-taking"],
  authors: [{ name: "NeuroNote Team" }],
  creator: "NeuroNote Team",
  openGraph: {
    type: "website",
    locale: "en_US",
    url: "https://neuronote.app",
    siteName: "NeuroNote",
    title: "NeuroNote - Knowledge Graph Note-Taking",
    description:
      "Build your personal knowledge graph with bidirectional linking and automatic entity extraction",
    images: [
      {
        url: "/og-image.png",
        width: 1200,
        height: 630,
        alt: "NeuroNote Preview",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "NeuroNote - Knowledge Graph Note-Taking",
    description:
      "Build your personal knowledge graph with bidirectional linking and automatic entity extraction",
    images: ["/og-image.png"],
  },
  robots: {
    index: true,
    follow: true,
  },
  icons: {
    icon: "/favicon.ico",
    shortcut: "/favicon-16x16.png",
    apple: "/apple-touch-icon.png",
  },
  manifest: "/site.webmanifest",
};

interface RootLayoutProps {
  children: ReactNode;
}

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${bodyFont.variable} ${mono.variable} ${serif.variable}`}
    >
      <body>
        <ToastProvider>
          <PreferencesProvider>
            {children}
            <ToastContainer />
          </PreferencesProvider>
        </ToastProvider>
      </body>
    </html>
  );
}
