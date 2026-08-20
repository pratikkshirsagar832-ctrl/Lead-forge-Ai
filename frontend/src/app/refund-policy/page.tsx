import type { Metadata } from 'next';
import { ContentPage, PolicySection } from '@/components/landing/ContentPage';

export const metadata: Metadata = {
  title: 'Refund & Cancellation Policy — Hyperclients',
  description: 'HyperClients refund and cancellation policy.',
};

export default function RefundPolicyPage() {
  return (
    <ContentPage kicker="Legal" title="Refund & Cancellation Policy">
      <p className="text-sm text-text-muted">
        Effective Date: August 10, 2026 · Platform: HyperClients (hyperclient.online)
      </p>

      <PolicySection title="1. No Refund Policy">
        <p>
          All purchases made on HyperClients are final and non-refundable. Once a payment has been successfully
          processed, no refunds, credits, or reversals will be issued under any circumstances.
        </p>
      </PolicySection>

      <PolicySection title="2. No Cancellations">
        <p>
          Subscription or plan cancellations do not entitle the user to a refund for the current billing period.
          Access to the platform will continue until the end of the paid period, after which renewal will not occur
          if cancelled.
        </p>
      </PolicySection>

      <PolicySection title="3. Failed Transactions">
        <p>
          In the event of a payment failure where your account has been debited but access has not been granted,
          please contact us immediately. We will investigate and resolve the issue within 5 to 7 business days.
        </p>
      </PolicySection>

      <PolicySection title="4. Disputes">
        <p>
          If you believe a charge was made in error, please reach out to us before raising a dispute with your bank
          or payment provider. Chargebacks initiated without prior communication may result in account suspension.
        </p>
      </PolicySection>

      <PolicySection title="5. Contact for Payment Issues">
        <ul className="list-disc pl-6 space-y-1.5">
          <li><strong className="text-offwhite">HyperClients</strong>, New Delhi, India</li>
          <li><strong className="text-offwhite">Contact:</strong> +91 9310642998</li>
          <li><strong className="text-offwhite">Email:</strong> contact@hyperclients.online</li>
        </ul>
      </PolicySection>
    </ContentPage>
  );
}