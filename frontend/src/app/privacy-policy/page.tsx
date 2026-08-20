import type { Metadata } from 'next';
import { ContentPage, PolicySection } from '@/components/landing/ContentPage';

export const metadata: Metadata = {
  title: 'Privacy Policy — Hyperclients',
  description: 'How Hyperclients collects, uses, and protects your personal data.',
};

export default function PrivacyPolicyPage() {
  return (
    <ContentPage kicker="Legal" title="Privacy Policy">
      <p className="text-sm text-text-muted">Effective Date: August 18, 2026 · Platform: HyperClients (hyperclient.online)</p>

      <PolicySection title="1. Introduction">
        <p>
          HyperClients (“we”, “us”, “our”) is committed to protecting your personal data. This Privacy Policy
          explains what data we collect, how we use it, and your rights under applicable Indian law including the
          Information Technology Act 2000, IT (Intermediary Guidelines and Digital Media Ethics Code) Rules 2021,
          and the Digital Personal Data Protection Act 2023.
        </p>
      </PolicySection>

      <PolicySection title="2. Data We Collect">
        <p>We may collect the following information:</p>
        <ul className="list-disc pl-6 space-y-1.5">
          <li>Name, email address, and phone number at registration</li>
          <li>Payment information (processed and stored by Razorpay — we do not store card details)</li>
          <li>Usage data and platform activity logs</li>
          <li>Device and browser information</li>
        </ul>
      </PolicySection>

      <PolicySection title="3. How We Use Your Data">
        <p>Your data is used to:</p>
        <ul className="list-disc pl-6 space-y-1.5">
          <li>Create and manage your HyperClients account</li>
          <li>Process payments via Razorpay</li>
          <li>Send transactional and service-related communications</li>
          <li>Improve platform performance and features</li>
        </ul>
      </PolicySection>

      <PolicySection title="4. Data Sharing">
        <p>We do not sell your personal data. We may share data with:</p>
        <ul className="list-disc pl-6 space-y-1.5">
          <li>Razorpay for payment processing</li>
          <li>Third-party analytics tools for platform improvement</li>
          <li>Legal authorities if required by law</li>
        </ul>
      </PolicySection>

      <PolicySection title="5. Data Retention">
        <p>
          We retain your personal data for as long as your account is active or as required by law. You may request
          deletion of your data by contacting us directly.
        </p>
      </PolicySection>

      <PolicySection title="6. Your Rights">
        <p>Under the DPDP Act 2023, you have the right to:</p>
        <ul className="list-disc pl-6 space-y-1.5">
          <li>Access the personal data we hold about you</li>
          <li>Correct inaccurate data</li>
          <li>Request erasure of your data</li>
          <li>Withdraw consent at any time</li>
        </ul>
      </PolicySection>

      <PolicySection title="7. Cookies">
        <p>
          HyperClients may use cookies and similar tracking technologies to improve user experience. You may disable
          cookies through your browser settings, though this may affect platform functionality.
        </p>
      </PolicySection>

      <PolicySection title="8. Security">
        <p>
          We implement reasonable technical and organisational measures to protect your data. However, no method of
          transmission over the internet is 100% secure.
        </p>
      </PolicySection>

      <PolicySection title="9. Grievance Officer">
        <p>
          In accordance with the Information Technology Act 2000 and IT Rules 2021, the details of the Grievance
          Officer are as follows:
        </p>
        <ul className="list-disc pl-6 space-y-1.5">
          <li><strong className="text-offwhite">Name:</strong> Bhaskar Gupta</li>
          <li><strong className="text-offwhite">Platform:</strong> HyperClients (hyperclient.online)</li>
          <li><strong className="text-offwhite">Contact:</strong> +91 9310642998</li>
          <li><strong className="text-offwhite">Email:</strong> contact@hyperclients.online</li>
        </ul>
        <p>
          Any grievances or complaints regarding data processing must be submitted to the Grievance Officer. We will
          acknowledge your complaint within 24 hours and resolve it within 15 days.
        </p>
      </PolicySection>

      <PolicySection title="10. Changes to This Policy">
        <p>
          We may update this Privacy Policy from time to time. Continued use of the platform after updates
          constitutes acceptance of the revised policy.
        </p>
      </PolicySection>
    </ContentPage>
  );
}