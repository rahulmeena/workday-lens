import type { Metadata } from "next";

import "./globals.css";
import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "Workday Lens",
  description: "A personal activity intelligence dashboard for understanding how your time was spent.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <main className="app-shell">
            <header className="app-header">
              <div>
                <p className="app-header__eyebrow">Personal Activity Intelligence</p>
                <h1>Workday Lens</h1>
              </div>
              <p className="app-header__tagline">Understand what your day became while you were doing it.</p>
            </header>
            <section className="app-content">{children}</section>
          </main>
        </Providers>
      </body>
    </html>
  );
}
