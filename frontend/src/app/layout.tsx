import type { Metadata } from 'next';
import { Montserrat, Space_Grotesk } from 'next/font/google';
import Script from 'next/script';
import '../styles/globals.css';
import { ThemeProvider } from '@/components/ThemeProvider';
import { ToastContainer } from '@/components/shared/Toast';
import { ThreeBackground } from '@/components/shared/ThreeBackground';

const montserrat = Montserrat({ subsets: ['latin'], variable: '--font-sans', weight: ['400', '500', '700', '800'] });
const spaceGrotesk = Space_Grotesk({ subsets: ['latin'], variable: '--font-heading', weight: ['400', '500', '600', '700'] });


export const metadata: Metadata = {
  title: 'Hyperclients',
  description: 'Automated Lead Generation Engine',
  icons: {
    icon: [
      { url: '/hyperclients-icon.svg', type: 'image/svg+xml' },
      { url: '/favicon.png', sizes: '32x32', type: 'image/png' },
    ],
    apple: [
      { url: '/apple-touch-icon.png' },
    ],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" data-scroll-behavior="smooth" suppressHydrationWarning>
      <body className={`${montserrat.className} ${spaceGrotesk.variable} min-h-screen bg-navy text-ice antialiased selection:bg-violet/30 selection:text-offwhite`}>
          <Script src="https://checkout.razorpay.com/v1/checkout.js" strategy="lazyOnload" />
          <script type="text/javascript">
            {`(function(c,l,a,r,i,t,y){
              c[a]=c[a]||function(){(c[a].q=c[a].q||[]).push(arguments)};
              t=l.createElement(r);t.async=1;t.src="https://www.clarity.ms/tag/"+i;
              y=l.getElementsByTagName(r)[0];y.parentNode.insertBefore(t,y);
            })(window, document, "clarity", "script", "xdko5ui3zm");`}
          </script>
          <script async src="https://www.googletagmanager.com/gtag/js?id=G-RVV56NV108"></script>
          <script>
            {`window.dataLayer = window.dataLayer || [];
            function gtag(){dataLayer.push(arguments);}
            gtag('js', new Date());
            gtag('config', 'G-RVV56NV108');`}
          </script>
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <ThreeBackground />
          {children}
          <ToastContainer />
        </ThemeProvider>
      </body>
    </html>
  );
}
