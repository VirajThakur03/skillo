# Marketplace Operating Spec

## 1. Microcopy And UX Writing System

### 1.1 Empty States

| Empty state | Headline | Subtext |
|---|---|---|
| No bookings | Nothing booked yet | Start with a quick search. Verified providers, clear pricing, and live tracking are ready when you are. |
| No providers found | No providers match this request | Try increasing your distance, removing one filter, or switching to a quote request for custom work. |
| No reviews | No reviews yet | This provider is new on the platform or has not completed enough jobs yet. Check verification, response time, and profile completeness before booking. |
| Empty chat | No messages yet | Send the first message to confirm scope, access instructions, or arrival details. Keep all job updates here for support protection. |
| Empty wallet | Your wallet is empty | Add a promo, earn referral credits, or complete a booking to see credits and refunds here. |
| Empty notifications | You're all caught up | Booking updates, quotes, payments, and support decisions will appear here as they happen. |
| No saved addresses | No saved addresses yet | Save home, office, or a family address now to book faster next time. |
| No favorites | No favorite providers yet | Save providers you trust so repeat bookings take one tap instead of another search. |
| No search results | No results for this search | Check your spelling, try a broader service name, or turn off “Open now” to see more options. |
| Calendar with no slots | No slots available right now | This provider has no bookable time in the selected window. Try another day or request a quote. |

### 1.2 Error Messages

| Scenario | Exact message | Recovery action |
|---|---|---|
| Payment failed | Your payment did not go through. Your slot is not confirmed yet. | Show `Try again` and `Use another payment method`. Keep the slot for 5 minutes if inventory allows. |
| Provider declined | This provider can't take your job at that time. | Show `See similar providers` and `Request a quote instead`. |
| Booking expired | This booking request expired because the time slot was released. | Show `Choose another slot`. Preserve entered job details. |
| Upload failed | We couldn't upload that file. Check your connection or try a smaller file. | Show `Retry upload`. Keep the rest of the form intact. |
| Location permission denied | Location access is off. Turn it on in settings or enter your area manually. | Show `Enter area manually` and `Open settings`. |
| Session timeout | For your security, you were signed out. Please log in again. | Show `Log in again`. Preserve the pre-login draft if possible. |
| Network error | The connection dropped. We could not complete that action. | Show `Try again`. If a draft exists, auto-save it locally. |

### 1.3 Confirmation Dialogs

| Action | Title | Body | Primary CTA | Secondary CTA |
|---|---|---|---|---|
| Cancel booking | Cancel this booking? | If you continue, cancellation charges may apply based on how close the booking is to the service time. We will show the refund before final confirmation. | `Review refund` | `Keep booking` |
| Delete account | Delete your account? | This will remove your profile access and sign you out on all devices. Bookings, invoices, and records we must retain by law will still be stored for the required period. | `Delete account` | `Go back` |
| Remove saved address | Remove this address? | This address will no longer appear at checkout. It will not affect past bookings linked to it. | `Remove address` | `Keep address` |
| Report a provider | Report this provider? | Your report will be reviewed by our Trust and Safety team. Submitting a false report may lead to account action. | `Submit report` | `Cancel` |
| Withdraw earnings | Withdraw earnings now? | The amount will be sent to your registered bank account. If there is an open dispute or hold, only the available balance can be withdrawn. | `Withdraw now` | `Not now` |

### 1.4 Onboarding Tooltips

| UI element | Tooltip label |
|---|---|
| Search bar | `Find local help` |
| Filter button | `Refine results` |
| Provider card | `Check trust first` |
| Favorite button | `Save for later` |
| Availability calendar | `See real slots` |
| Quote request button | `Ask custom price` |
| Chat button | `Message safely here` |
| Live tracker | `Track arrival live` |

### 1.5 Push Notification Copy

| Event | Copy |
|---|---|
| Booking confirmed | Booking confirmed. Your provider is set. |
| Provider en route | Your provider is on the way. Track live. |
| Provider arrived | Your provider has arrived. |
| Booking completed | Job completed. Rate your service now. |
| Payment received | Payment received. Booking is confirmed. |
| New message | New message in your booking chat. |
| Quote received | New quote received. Compare and book. |
| Dispute resolved | Dispute resolved. See the final update. |

### 1.6 Tone Guidelines

| Rule | Do | Don't |
|---|---|---|
| Be calm under pressure | `Your payment did not go through. Try again or use another method.` | `Payment failed. Something went wrong.` |
| Be specific about next steps | `Turn on location or enter your area manually.` | `Please fix the issue and try again.` |
| Be transparent about money | `A ?100 late-cancel fee applies if you cancel now.` | `Charges may apply.` |
| Respect both sides of the marketplace | `This provider can't take your job at that time.` | `The provider rejected you.` |
| Use plain Indian English | `Save this address for faster checkout next time.` | `Persist this location artifact for future transactions.` |

## 2. Onboarding Flows

### 2.1 Seeker Onboarding

1. Welcome and role choice
2. Mobile number and OTP verification
3. Name capture
4. Optional location starter
5. Search and filter discovery
6. Provider detail with verification, ratings, and compare
7. Slot picker or quote request mode
8. Address and payment at checkout
9. Confirmation with chat, tracking, and support path

Activation milestone: seeker reaches `booking_confirmed` within the first session or within 24 hours of the first booking attempt.

48-hour re-engagement:
- Push: `Need help choosing? Try verified providers near you.`
- In-app card: `Finish your first booking in under 2 minutes. Start with top-rated providers in your area.`
- Email or WhatsApp: `Still deciding? Compare verified providers, see real prices, or request a custom quote.`

### 2.2 Provider Onboarding

1. Welcome and role choice
2. Mobile number and OTP
3. Name, city, and service category selection
4. Profile setup with bio, experience, languages, and work photos
5. ID verification, selfie, and liveness
6. Skill verification where required
7. Bank and payout setup
8. Availability and pricing setup
9. Soft launch review state
10. Go-live confirmation and provider agreement acceptance

Required documents:
- PAN
- one government ID with DOB
- selfie and liveness capture
- category-specific license or certificate where relevant
- bank verification

Soft launch state: searchable but not bookable until identity, bank, availability, and agreement requirements are complete.

Provider activation milestone: provider is live once verification, bank setup, availability, and agreement acceptance are complete, and activated when the first job is accepted within 14 days.

## 3. Legal And Compliance Layer

### 3.1 Terms And Conditions

Mandatory clauses:
1. cancellation and reschedule rules
2. liability cap
3. prohibited services
4. dispute resolution
5. intellectual property
6. provider classification
7. payment terms
8. refund policy
9. force majeure
10. governing law
11. amendments
12. account termination

### 3.2 Privacy Policy

Data categories:
- account data
- identity verification data
- booking and address data
- payment references
- chat and dispute evidence
- live tracking and device signals
- reviews and notification preferences

Recommended retention:
- booking, invoice, and settlement records: 8 years
- chat and dispute evidence: 3 years after closure
- raw location pings: 90 days
- successful verification media: 180 days
- failed verification media: 90 days

User rights in a DPDPA-aligned operating model:
- access summary
- correction
- completion
- erasure when legally possible
- consent withdrawal where relevant
- grievance redressal

### 3.3 Provider Agreement

- independent contractor status
- commission and payout clauses
- conduct and quality standards
- background and fraud screening consent
- off-platform payment diversion ban
- customer data handling restrictions
- termination triggers

### 3.4 Refund Matrix

| Scenario | Seeker refund | Provider payout | SLA |
|---|---|---|---|
| Cancel >24h | 100% refund | 0 | Initiate in 1 hour |
| Cancel 2h to 24h | Refund minus 10%, minimum ?100 | 0 | Initiate in 1 hour |
| Cancel <2h | Refund minus 25%, minimum ?250 | 0 | Initiate in 1 hour |
| Provider cancel | 100% refund + ?100 goodwill credit | 0 | Initiate in 1 hour |
| Provider no-show | 100% refund + ?150 goodwill credit | 0 | Initial review in 4 hours |
| Seeker no-show | Usually no refund | Protected visit fee or minimum may apply | 24 hours with evidence |
| Disputed job | 25% to 100% refund based on evidence | Partial, held, or zero payout | Final within 5 business days |

### 3.5 Age Verification

- providers must be 18+
- DOB must be checked against a government ID
- selfie or liveness must match the document holder
- under-18 provider onboarding must be rejected

### 3.6 GST And Income-Tax Notes

- Section 194-O is income-tax TDS, not GST TCS
- GST TCS sits under Section 52 of the CGST Act where applicable
- payout statements must show commission, GST on commission, and 194-O deduction

### 3.7 Data Localization

- DPDPA 2023 does not create a blanket India-only localization rule
- RBI payment data localization still applies to payment system data
- Sklio should keep primary operational data on Indian infrastructure for trust and operational simplicity

### 3.8 Grievance Officer

- acknowledge complaints within 24 hours
- standard resolution target within 15 days
- trust or safety escalation within 4 hours
- publish contact email, office address, and escalation path

### 3.9 Reference Set

- DPDPA 2023: https://www.indiacode.nic.in/handle/123456789/22037?view_type=browse
- IT Rules 2021: https://www.meity.gov.in/static/uploads/2024/02/Intermediary_Guidelines_and_Digital_Media_Ethics_Code_Rules-2021.pdf
- Income-tax threshold page: https://www.incometaxindia.gov.in/w/threshold-limits-under-income-tax-act
- CBDT Circular 17/2020: https://www.incometaxindia.gov.in/communications/circular/circular_17_2020.pdf
- GST TCS FAQ: https://cbic-gst.gov.in/pdf/FAQs-TCS-30-11-2018.pdf
- RBI payment data localization: https://rbi.org.in/Scripts/NotificationUser.aspx?Id=11244

## 4. Competitor Benchmark

| Competitor | Core booking flow | Trust signals | Membership | Smart features | Key pattern to adopt | Friction to avoid |
|---|---|---|---|---|---|---|
| Urban Company | roughly 5 to 7 taps after location setup | pricing, verified pros, warranty, dense ratings | yes | operational standardization | fixed packages and trust-led checkout | too much rigidity for custom work |
| TaskRabbit | roughly 6 to 7 taps with async Tasker confirmation | rates, reviews, secure payment, policy clarity | no clear consumer plan | matching and scheduling | structured chat and clear ops policies | async confirmation uncertainty |
| Thumbtack | roughly 5 to 7 taps with Instant Book, more if chat-first | guarantee, reviews, licensed badges | no obvious consumer plan | strong guidance and matching | compare-first search UX | uneven transparency on vetting depth |
| Housejoy | roughly 4 to 6 steps, more lead-gen than instant-book | testimonials and refund page | not prominent | no visible AI layer | broad category coverage | weaker trust instrumentation at checkout |

Gap analysis:
- stronger visible guarantee layer
- more explicit licensed and verified badges
- more polished compare-first decision support
- deeper service-package standardization for repeat categories
- tighter post-job review and tip loop

Differentiation opportunities:
- chat plus live tracking in one journey
- quote mode and instant book side by side
- India-specific trust, payout, and tax clarity
- provider growth tooling tied to ranking and earnings
- AI assist across intake, matching, chat, and review signals

Category killer feature:
- Home Asset Passport

## 5. Launch Readiness Checklist

### 5.1 Product
- UAT across search, compare, booking, quotes, chat, tracking, notifications, disputes, and reviews
- 95% UAT pass rate with no Sev-1 or Sev-2 blockers
- feature-flag rollback path for quotes, memberships, referrals, and AI assist

### 5.2 Engineering
- search p95 under 500 ms
- booking create p95 under 800 ms
- chat send failure under 0.5%
- 5xx rate under 1%
- alerting and on-call playbooks in place

### 5.3 Design
- final QA on onboarding, search, booking, chat, tracking, dashboards
- WCAG 2.1 AA review
- empty-state and reduced-motion coverage

### 5.4 Legal
- Terms, Privacy, Refund Policy, and Provider Agreement published
- GST and tax position reviewed
- grievance flow published

### 5.5 Ops
- at least 25 live providers per launch city-category
- category SOPs written
- CS team trained on refunds, payouts, disputes, and verification

### 5.6 Marketing
- app store metadata and screenshots complete
- trust-led landing pages ready
- launch creatives and referral budget approved

### 5.7 Data
- key events validated
- activation, booking, dispute, and city launch dashboards live
- alert thresholds configured

### 5.8 Support
- helpdesk queues configured
- FAQ published
- escalation path documented
- first 48-hour war room plan staffed

## 6. Monetization Logic

### 6.1 Commission Structure

| Category | New provider | Growth provider | Trusted provider |
|---|---:|---:|---:|
| Cleaning | 18% | 16% | 14% |
| Plumbing / Electrician / Carpenter | 15% | 13% | 11% |
| Appliance repair / AC | 14% | 12% | 10% |
| Beauty / Wellness | 20% | 18% | 16% |
| Tutoring / consultation | 12% | 10% | 8% |

Surge rules:
- coverage ratio below 1.15
- same-day fill above 85%
- seeker uplift capped at 25%
- 70% of surge to provider, 30% to platform

### 6.2 Subscription Tiers

| Tier | Price | Benefits |
|---|---:|---|
| Free | ?0 | standard search, booking, quotes, chat |
| Plus | ?149/month | lower service fee up to 5%, one late-cancel waiver per quarter, 2% cashback |
| Premium | ?399/month | lower service fee up to 10%, two reschedule waivers per quarter, priority support, 5% cashback |

Provider membership:
- `Pro Provider` at ?499/month
- lower commission by 2 points
- visibility boost
- priority matching
- advanced analytics
- faster payout eligibility

### 6.3 Revenue Template

Assumptions:
- average order value ?1,200
- gross take rate 18%
- net take rate 14%

| Daily bookings | Monthly GMV | Gross revenue | Net revenue |
|---:|---:|---:|---:|
| 100 | ?36,00,000 | ?6,48,000 | ?5,04,000 |
| 500 | ?1,80,00,000 | ?32,40,000 | ?25,20,000 |
| 1000 | ?3,60,00,000 | ?64,80,000 | ?50,40,000 |

## 7. Provider Growth Playbook

CAC ranking:
1. provider referrals
2. WhatsApp trade groups
3. trade associations
4. field teams
5. digital ads

Lifecycle stages:
- Prospect
- Onboarding
- Active
- Top-rated
- Churned

Activation tactics:
- completion nudges
- missed-opportunity cards
- assisted onboarding support
- temporary lead credits
- price benchmarking guidance

Level-up mechanics:
- Bronze
- Silver
- Gold
- Platinum

## 8. Abuse And Fraud Prevention

| Fraud vector | Trigger | Detection method | Automated response | Human review threshold | Penalty |
|---|---|---|---|---|---|
| Fake bookings | repeated late cancels | cancel-rate model | deposit-only mode | 5 cancels in 30 days | warning to suspension |
| Review manipulation | linked accounts or review burst | graph and text similarity | quarantine reviews | 3 suspicious reviews | removal to suspension |
| Identity fraud | ID mismatch or reused document hash | OCR and liveness checks | freeze onboarding | any critical mismatch | reject or ban |
| Refund abuse | repeated weak-evidence disputes | dispute model plus evidence cross-check | hold refund pending evidence | 3 disputes in 60 days | warning to suspension |
| Price collusion | abnormal city-category price spike | anomaly clustering | ranking suppression | 5 connected providers | warning to removal |
| Account takeover | risky login plus payout change | device fingerprint and impossible travel | step-up auth and temporary lock | any high-risk payout edit | temporary lock |
| Cash diversion | off-platform payment language | keyword and pattern detection | warning banner and investigation | 2 signals plus complaint | warning to ban |
| Fake profiles | same device, bank, or ID reused | entity-resolution graph | freeze newer account | any KYC overlap | ban cluster |

## 9. Accessibility Audit Spec

- minimum tap target 48x48 dp on mobile and 44x44 px on web admin
- body text contrast 4.5:1
- no status by color alone
- keyboard access for all critical admin flows
- reduced-motion mode must suppress parallax, pulses, and celebratory animation
- screen reader coverage required on onboarding, search, provider detail, slot picker, checkout, chat, tracking, and provider verification

## 10. Data And Analytics Plan

Core event families:
- acquisition and identity
- discovery and consideration
- quote and booking
- engagement, trust, and provider ops

Core funnels:
- seeker activation
- provider activation
- booking completion
- dispute resolution

Retention targets:
- seekers: D1 25%, D7 12%, D30 6%
- providers: D1 40%, D7 25%, D30 15%

Provider quality score:
`PQS = 100 x [0.30 x completion_rate + 0.25 x (average_rating / 5) + 0.15 x response_score + 0.15 x on_time_arrival_rate + 0.10 x (1 - cancellation_rate) + 0.05 x (1 - dispute_rate)]`

Supply-demand health:
`Coverage Ratio = Bookable provider-hours next 7 days / Forecasted demand-hours next 7 days`

Dashboards:
- ops
- growth
- trust
- finance
- city launch
- AI performance
