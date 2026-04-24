# Quick Start Action Plan — Next 30 Days

**Decision:** You've decided to build Instagram automation (Path A: Meta Official API)

**Timeline:** 30 days until Sprint 1 is underway

---

## Week 1: Foundation & Setup

### Day 1-2: Legal & Compliance Prep

- [ ] **Draft Privacy Policy** (if not already done)
  - Include: How you collect data, store tokens, handle DMs, comply with GDPR/LGPD
  - Reference: [Meta's Privacy Policy Guide](https://www.facebook.com/policies)
  - Time: 2-4 hours (or hire lawyer)

- [ ] **Create Terms of Service** for Instagram feature
  - Include: 200 DM/hour limits, API reliability disclaimers, data deletion policy
  - Time: 2-4 hours

### Day 3-5: Meta Developer Setup

- [ ] **Create Meta Business Account** (if not already)
  - Go to [business.facebook.com](https://business.facebook.com)
  - Verify phone + email
  - Create workspace

- [ ] **Create Meta for Developers App**
  - Go to [developers.facebook.com](https://developers.facebook.com)
  - Create app (type: Business)
  - Name: "[YourCompany] Instagram Bot"
  - Category: Business
  - Time: 30 mins

- [ ] **Begin Business Verification**
  - In Business Manager, go to Settings → Business Verification
  - Upload: ID, CNPJ (se Brasil), address proof, tax docs
  - Time: 1-2 hours (docs gathering)
  - Timeline: 1-2 days to approve

- [ ] **Request Instagram Graph API Access**
  - In Meta for Developers, add Instagram Graph API
  - Request permissions:
    - `instagram_manage_messages`
    - `instagram_read_messages`
    - `pages_manage_messages`
    - `pages_read_messaging`
  - Time: 15 mins

---

## Week 2: Technical Preparation

### Day 8-9: Architect & Plan

- [ ] **API Endpoint Design Doc**
  - Design: `/api/accounts/{accountId}/instagram/link` (OAuth start)
  - Design: `/api/flows/{flowId}/instagram/send-message`
  - Design: `/webhook/instagram` (webhook receiver)
  - Time: 3-4 hours (Draft with tech lead)

- [ ] **Webhook Infrastructure Plan**
  - Decide: Cloud provider (AWS Lambda, GCP Cloud Functions, Azure)
  - Plan: HTTPS endpoint (must be public)
  - Plan: Secret token storage (env var, Vault, secrets manager)
  - Time: 2 hours

- [ ] **Database Schema Add-ons**
  - Plan new columns: `instagram_account_id`, `oauth_token`, `api_rate_limit_used`, `api_rate_reset_at`
  - Plan new tables: `instagram_comments`, `webhook_events`
  - Time: 2 hours

### Day 10-12: Development Environment Setup

- [ ] **Create Development Instagram Account**
  - Create test IG account (your company)
  - Convert to Business/Creator profile
  - Link to Facebook Page (required for API)
  - Time: 30 mins

- [ ] **Set Up Webhook Testing Locally**
  - Install ngrok or localtunnel
  - Test webhook signature validation
  - Time: 1 hour

- [ ] **Skeleton Code**
  - Initialize `InstagramAdapter` class (Python/Node)
  - Initialize webhook handler
  - Initialize flow executor router
  - Commit to repo
  - Time: 3-4 hours

---

## Week 3: OAuth & Integration

### Day 15-17: OAuth Flow Implementation

- [ ] **OAuth Consent Screen**
  - In Meta for Developers, configure OAuth Redirect URIs
  - Add: `https://yourapp.com/auth/instagram/callback`
  - Time: 30 mins

- [ ] **OAuth Implementation**
  - Implement: User clicks "Connect Instagram"
  - Implement: Redirects to Meta OAuth URL
  - Implement: Handle callback, store access token + expires_at
  - Implement: Token refresh logic (expires every 60 days)
  - Time: 6-8 hours (dev)

- [ ] **Test OAuth Flow**
  - With dev account, go through full auth flow
  - Verify token stored + retrieved correctly
  - Test token refresh
  - Time: 2 hours (QA)

### Day 18-19: Message Sending (Basic)

- [ ] **Implement `send_message()`**
  - Text only
  - Image attachment
  - Handle responses (success/error/rate-limit)
  - Time: 4-6 hours (dev)

- [ ] **Test Message Sending**
  - Send DMs from your service to your dev account
  - Verify appears in Instagram UI
  - Test image attachments
  - Time: 2 hours (QA)

---

## Week 4: Webhook & First Full Integration

### Day 22-24: Webhook Setup

- [ ] **Implement Webhook Receiver**
  - POST endpoint that validates Meta signature
  - Routes events: messages, comments, story_replies, story_mentions
  - Queues events to background job
  - Time: 4 hours (dev)

- [ ] **Subscribe to Webhook Events**
  - In Meta for Developers, Webhooks section
  - Add callback URL (your HTTPS endpoint)
  - Subscribe to events: `messages`, `messaging_postbacks`, `message_echoes`
  - Time: 1 hour

- [ ] **Test Webhook Delivery**
  - Send DM to your bot from your dev account
  - Verify webhook fires
  - Verify event data correct
  - Time: 2 hours (QA)

### Day 25-27: Flow Executor Adaptation

- [ ] **Adapt Flow Executor for Instagram**
  - Add platform router (WhatsApp vs Instagram)
  - Adapt Menu node to use quick_replies (vs buttons WhatsApp)
  - Test existing flows execute in IG mode
  - Time: 8-10 hours (dev)

### Day 28-30: Documentation & Cleanup

- [ ] **Code Review & Cleanup**
  - Code review with team
  - Fix style issues, add comments
  - Time: 2-3 hours

- [ ] **README & API Docs**
  - Document: How to connect Instagram account
  - Document: Rate limits, error codes
  - Document: OAuth flow
  - Time: 3-4 hours

- [ ] **Prepare for App Review Submission**
  - Collect screenshots of key flows
  - Write description: "This app helps businesses automate Instagram DMs"
  - Prepare privacy policy link
  - Time: 2-3 hours

---

## Week 5: Meta App Review Submission (Happens in parallel)

### Day 31-35: Formal App Review

- [ ] **Gather Required Materials**
  - 2-3 minute video screencast:
    - Show logging in with Instagram
    - Show sending a message
    - Show flow executing
  - Privacy policy (already drafted)
  - Description (already written)
  - Time: 1-2 hours

- [ ] **Submit for Meta App Review**
  - Go to Meta for Developers → App Review
  - Submit the `instagram_manage_messages` scope
  - Upload video + docs
  - Time: 30 mins

- [ ] **Wait for Review**
  - Expected: 2-4 weeks
  - Meanwhile: Continue Sprint 2 work (comment triggers, story replies)
  - Meta may ask clarifying questions (respond within 2 days)

---

## Parallel Track: Customer Preparation

### All 4 Weeks: Pitch & Validation

- [ ] **Validate with Top 3 WhatsApp Customers**
  - Call them: "We're building Instagram automation, interested?"
  - Show mockup/demo of flow builder for IG
  - Gauge: Would they pay $29/mo for this?
  - Document: List of "early-access" candidates
  - Time: 2-3 hours

- [ ] **Create Sales One-Pager**
  - Title: "Instagram Automation Flows"
  - Bullet points: Comment→DM, Story replies, Ice Breakers
  - Comparison table vs competitors (ManyChat, Chatfuel)
  - Pricing: $29/mo per account
  - Time: 2 hours

---

## Checklist: End of 30 Days

- [ ] Meta Business Account verified
- [ ] Meta for Developers app created
- [ ] Instagram Graph API permissions requested
- [ ] OAuth flow fully implemented & tested
- [ ] Message sending working (text + images)
- [ ] Webhook receiver implemented & subscribed
- [ ] Flow executor routing Instagram support
- [ ] 5+ screenshots collected for app review
- [ ] App review submitted to Meta
- [ ] Privacy policy + Terms of Service finalized
- [ ] 3+ customers pre-qualified as early adopters
- [ ] Sales one-pager created
- [ ] Dev team ready for Sprint 2 (comments, story)
- [ ] Code pushed to main repo, all tests green

---

## Resource Allocation

| Role | Time Commitment | Duration |
|---|---|---|
| **Backend Engineer** | 40h/week | 4 weeks |
| **Product Manager** | 10h/week | 4 weeks |
| **QA Engineer** | 15h/week | 3 weeks (starts week 2) |
| **Legal/Compliance** | 5h/week | 1 week |

**Total: ~1.5 FTE for 30 days**

---

## Success Metrics (End of Week 4)

1. ✅ Can send DMs programmatically via Meta API
2. ✅ OAuth flow is seamless (one-click Instagram connect)
3. ✅ Webhooks reliably deliver DM events
4. ✅ Flow executor routes Instagram flows (MVP)
5. ✅ App review submitted (expect approval Week 8-12)
6. ✅ 3+ customers interested + waiting for approval

---

## Risk Mitigation

| Risk | Mitigation | Responsible |
|---|---|---|
| Meta app review rejected | Have lawyer review privacy policy upfront | Legal |
| OAuth token storage vulnerability | Use env vars + secrets manager, never log tokens | Backend |
| Webhook rate-limiting issues | Implement exponential backoff + queue | Backend |
| Flow executor refactoring too slow | Use feature flags to toggle IG mode | Backend |

---

## Next Document to Read

After completing Week 1:
- Read **Full Analysis Report** (`instagram_automation_report.md`)
- Focus on: Section 5 (Caminhos), Section 6 (Arquitetura)

After completing Week 2:
- Review: Section 2 (Features table) + Section 10 (Code examples)

After Meta approval:
- Ready to launch Sprint 2 (Section 7)

---

**Good luck!** 

Contact point: [Your tech lead email]  
Status updates: Weekly standup every Monday  
Review checkpoint: End of Week 2 (Day 12) — assess if on track

