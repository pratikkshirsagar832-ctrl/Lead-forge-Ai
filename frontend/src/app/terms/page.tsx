import type { Metadata } from 'next';
import { ContentPage, PolicySection } from '@/components/landing/ContentPage';

export const metadata: Metadata = {
  title: 'Terms & Conditions — Hyperclients',
  description: 'The terms governing your use of the HyperClients platform.',
};

export default function TermsPage() {
  return (
    <ContentPage kicker="Legal" title="Terms & Conditions">
      <p className="text-sm text-text-muted">
        Effective Date: August 10, 2026 · Platform: HyperClients (hyperclient.online) · Operated by: Radian Marketing
      </p>

      <PolicySection title="1. Acceptance of Terms">
        <p>
          By accessing or using HyperClients, you agree to be bound by these Terms and Conditions. If you do not
          agree, please do not use the platform.
        </p>
      </PolicySection>

      <PolicySection title="2. Description of Service">
        <p>
          HyperClients is a local business intelligence and lead generation platform that surfaces contact data and
          intent signals from publicly available Google My Business profiles. The platform is intended for use by
          agencies, freelancers, and sales professionals.
        </p>
      </PolicySection>

      <PolicySection title="3. Eligibility">
        <p>
          You must be at least 18 years of age and capable of entering into a legally binding agreement to use this
          platform. By using HyperClients, you confirm that you meet these requirements.
        </p>
      </PolicySection>

      <PolicySection title="4. User Responsibilities">
        <p>You agree to:</p>
        <ul className="list-disc pl-6 space-y-1.5">
          <li>Use the platform only for lawful business purposes</li>
          <li>Not resell, redistribute, or sublicense data obtained through HyperClients without prior written consent</li>
          <li>Not use the platform to spam, harass, or contact businesses in violation of applicable laws</li>
          <li>Provide accurate information during registration and payment</li>
        </ul>
      </PolicySection>

      <PolicySection title="5. Payments">
        <p>
          All payments are processed securely through Razorpay. By completing a purchase, you agree to Razorpay&apos;s
          terms of service in addition to these terms. All prices are listed in Indian Rupees (INR) unless stated
          otherwise.
        </p>
      </PolicySection>

      <PolicySection title="6. No Refund Policy">
        <p>
          All sales on HyperClients are final. We do not offer refunds, partial credits, or exchanges once a purchase
          has been made. Please review your plan carefully before completing payment.
        </p>
      </PolicySection>

      <PolicySection title="7. Intellectual Property">
        <p>
          All content, branding, and technology on HyperClients is the property of Radian Marketing. You may not copy,
          reproduce, or reverse engineer any part of the platform.
        </p>
      </PolicySection>

      <PolicySection title="8. Limitation of Liability">
        <p>
          Radian Marketing shall not be held liable for any direct, indirect, incidental, or consequential damages
          arising from your use of HyperClients or the data obtained through it. The platform provides publicly
          available data and does not guarantee accuracy or completeness.
        </p>
      </PolicySection>

      <PolicySection title="9. Termination">
        <p>
          We reserve the right to suspend or terminate your account at our discretion if you are found to be in
          violation of these terms.
        </p>
      </PolicySection>

      <PolicySection title="10. Governing Law">
        <p>
          These Terms are governed by the laws of India. Any disputes shall be subject to the exclusive jurisdiction
          of courts in New Delhi.
        </p>
      </PolicySection>

      <PolicySection title="11. Changes to Terms">
        <p>
          Hyperclients reserves the right to update these Terms at any time. Continued use of the platform after
          changes constitutes acceptance of the revised Terms.
        </p>
      </PolicySection>

      <PolicySection title="12. Contact">
        <p>For any queries regarding these Terms, contact us at:</p>
        <ul className="list-disc pl-6 space-y-1.5">
          <li><strong className="text-offwhite">HyperClients</strong>, New Delhi, India</li>
          <li><strong className="text-offwhite">Contact:</strong> +91 9310642998</li>
          <li><strong className="text-offwhite">Email:</strong> contact@hyperclients.online</li>
        </ul>
      </PolicySection>
    </ContentPage>
  );
}