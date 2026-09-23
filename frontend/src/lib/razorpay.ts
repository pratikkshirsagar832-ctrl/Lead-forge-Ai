/* Razorpay checkout loader shared by pages that take payments. */

export interface RazorpayResponse {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}

export interface RazorpayError {
  error?: { description?: string };
}

export type RazorpayCtor = {
  new (options: Record<string, unknown>): {
    on: (event: string, handler: (response: unknown) => void) => void;
    open: () => void;
  };
};

/** Resolve the Razorpay constructor, injecting checkout.js when it is missing
 * (ad-blockers / slow networks). Resolves undefined after `timeoutMs`. */
export function ensureRazorpayLoaded(timeoutMs = 12000): Promise<RazorpayCtor | undefined> {
  return new Promise((resolve) => {
    const w = window as unknown as { Razorpay?: RazorpayCtor };
    if (w.Razorpay) {
      resolve(w.Razorpay);
      return;
    }
    if (!document.querySelector('script[src*="checkout.razorpay.com"]')) {
      const s = document.createElement('script');
      s.src = 'https://checkout.razorpay.com/v1/checkout.js';
      s.async = true;
      document.head.appendChild(s);
    }
    const started = Date.now();
    const timer = setInterval(() => {
      if (w.Razorpay) {
        clearInterval(timer);
        resolve(w.Razorpay);
      } else if (Date.now() - started > timeoutMs) {
        clearInterval(timer);
        resolve(undefined);
      }
    }, 250);
  });
}
