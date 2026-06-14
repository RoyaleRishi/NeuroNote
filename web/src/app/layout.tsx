import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Newsreader } from "next/font/google";
import "katex/dist/katex.min.css";
import "../styles/tokens.css";
import "./globals.css";
import { ToastProvider } from "../lib/toast";
import { ToastContainer } from "../components/ui/ToastContainer";
import { PreferencesProvider } from "../lib/preferences/PreferencesProvider";

/**
 * Warm serif used exclusively for the note editor surface (see
 * `--font-family-serif` in tokens.css). UI chrome stays on the sans body
 * stack. Exposed as the `--font-serif-next` CSS variable.
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
    <html lang="en" className={serif.variable}>
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
