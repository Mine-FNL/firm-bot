"""Generate a curated multi-document contract corpus for the benchmark.

Five contracts with varied structure:
- Standard MSA with articles (numbered)
- NDA with definitions
- Service agreement with ALL CAPS section titles
- Settlement agreement (short)
- Employment agreement (mix of headings + numbered clauses)

Each contains a "needle" clause that the benchmark can target with a
specific question.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)


def build_pdf(out: Path, title: str, sections: list[tuple[str, str]]) -> None:
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18, leading=22, spaceAfter=12)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=14, leading=18, spaceAfter=8)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=11, leading=14, spaceAfter=6)
    doc = SimpleDocTemplate(
        str(out),
        pagesize=LETTER,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
    )
    flow: list[Any] = [Paragraph(title, h1), Spacer(1, 12)]
    for heading, body_text in sections:
        flow.append(Paragraph(heading, h2))
        for p in body_text.split("\n\n"):
            flow.append(Paragraph(p.replace("\n", " "), body))
        flow.append(Spacer(1, 6))
    doc.build(flow)


CORPUS: list[dict[str, Any]] = [
    {
        "name": "globex_msa.pdf",
        "title": "Globex Master Services Agreement",
        "sections": [
            (
                "Article I — Definitions",
                "Confidential Information means any non-public information disclosed by one party to the other in writing or orally that is designated as confidential or that should reasonably be understood to be confidential given the nature of the information and the circumstances of disclosure. Force Majeure Event means any event beyond a party's reasonable control, including acts of God, war, terrorism, civil unrest, and natural disasters. Business Day means any day other than a Saturday, Sunday, or legal holiday on which banks in New York, New York are authorized or required by law to be closed.",
            ),
            (
                "Article II — Services",
                "Vendor shall provide the services described in one or more Statements of Work executed by the parties. Each SOW shall set forth the scope, deliverables, timeline, and fees.",
            ),
            (
                "Section 4.2 — Limitation of Liability",
                "EXCEPT FOR BREACHES OF CONFIDENTIALITY OR INDEMNIFICATION OBLIGATIONS, NEITHER PARTY'S AGGREGATE LIABILITY ARISING OUT OF OR RELATED TO THIS AGREEMENT SHALL EXCEED THE FEES PAID BY CUSTOMER TO VENDOR IN THE TWELVE (12) MONTHS PRECEDING THE EVENT GIVING RISE TO THE CLAIM. IN NO EVENT SHALL EITHER PARTY BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, OR CONSEQUENTIAL DAMAGES.",
            ),
            (
                "Section 6.1 — Indemnification",
                "Vendor shall indemnify, defend, and hold harmless Customer from any third-party claims arising out of Vendor's gross negligence or wilful misconduct, or any breach of Vendor's confidentiality obligations under Article I.",
            ),
            (
                "Section 8.4 — Termination",
                "Either party may terminate this Agreement for material breach upon thirty (30) days' written notice if the breach remains uncured at the end of such period. Customer may also terminate any Statement of Work for convenience upon fifteen (15) days' written notice.",
            ),
            (
                "Schedule A — Fee Schedule",
                "Hourly rates: Senior Partner $750/hour, Partner $550/hour, Senior Associate $400/hour, Associate $275/hour, Paralegal $150/hour. Fixed fees for routine filings available on request.",
            ),
        ],
    },
    {
        "name": "initech_nda.pdf",
        "title": "Initech Mutual Non-Disclosure Agreement",
        "sections": [
            (
                "Definitions",
                "Confidential Information means information disclosed by either party that is marked confidential or that a reasonable person would understand to be confidential. The receiving party shall use Confidential Information only for the Purpose.",
            ),
            (
                "Permitted Disclosures",
                "The receiving party may disclose Confidential Information to its employees, contractors, and professional advisors who have a need to know and are bound by confidentiality obligations no less protective than those herein.",
            ),
            (
                "Term",
                "This Agreement shall remain in effect for three (3) years from the Effective Date. Confidentiality obligations shall survive termination for an additional five (5) years.",
            ),
            (
                "Governing Law",
                "This Agreement is governed by the laws of the State of Delaware, without regard to its conflict-of-laws principles.",
            ),
        ],
    },
    {
        "name": "umbrella_settlement.pdf",
        "title": "Umbrella Corp Settlement Agreement",
        "sections": [
            (
                "RECITALS",
                "WHEREAS the parties have engaged in disputes regarding the 2024 commercial transaction; and WHEREAS the parties wish to settle all such disputes without admission of liability; NOW THEREFORE the parties agree as follows.",
            ),
            (
                "1. Settlement Amount",
                "Umbrella Corp shall pay Hooli Inc. the sum of two million four hundred thousand dollars ($2,400,000) within thirty (30) days of the Effective Date, by wire transfer to the account designated in writing by Hooli.",
            ),
            (
                "2. Mutual Release",
                "Upon receipt of the Settlement Amount, each party releases the other from any claims arising before the Effective Date relating to the 2024 commercial transaction.",
            ),
            (
                "3. Confidentiality of Settlement",
                "The parties shall keep the terms of this Settlement strictly confidential and shall not disclose them to any third party except as required by law or to professional advisors bound by confidentiality.",
            ),
        ],
    },
    {
        "name": "wayne_employment.pdf",
        "title": "Wayne Enterprises Executive Employment Agreement",
        "sections": [
            (
                "1. Position and Duties",
                "Employee shall serve as Chief Executive Officer of the Company and shall perform the duties customarily performed by a chief executive officer of a comparably-sized enterprise.",
            ),
            (
                "2. Base Salary",
                "The Company shall pay Employee an annual base salary of one million five hundred thousand dollars ($1,500,000), payable in equal monthly installments.",
            ),
            (
                "3. Annual Bonus",
                "Employee shall be eligible for an annual performance bonus of up to two hundred percent (200%) of Base Salary, determined by the Compensation Committee based on Company and individual performance.",
            ),
            (
                "4. Severance",
                "If the Company terminates Employee's employment without Cause, the Company shall pay Employee severance equal to twenty-four (24) months of Base Salary, plus continuation of health benefits for the severance period.",
            ),
        ],
    },
    {
        "name": "stark_audit.pdf",
        "title": "Stark Industries Audit Engagement Letter",
        "sections": [
            (
                "Engagement Overview",
                "Auditor will perform an audit of the Company's consolidated balance sheet as of December 31, 2026 and the related statements of operations, stockholders' equity, and cash flows for the year then ended.",
            ),
            (
                "Audit Fee",
                "The fee for the audit shall not exceed four hundred fifty thousand dollars ($450,000) plus reasonable out-of-pocket expenses, billed monthly as work progresses.",
            ),
            (
                "Reportable Conditions",
                "Auditor will communicate to the Audit Committee any reportable conditions involving internal controls that come to Auditor's attention during the engagement.",
            ),
            (
                "Confidentiality",
                "Auditor will treat all client information as strictly confidential and will use it solely for purposes of performing the engagement.",
            ),
        ],
    },
    # ---- longer / adversarial documents ----
    {
        "name": "acme_msa_long.pdf",
        "title": "Acme Industries Master Services Agreement (Long Form)",
        "sections": [
            (
                "Article I — Definitions",
                "Confidential Information means any non-public information disclosed by one party to the other in writing or orally that is designated as confidential. The receiving party shall use Confidential Information only for the Purpose. The parties acknowledge that the disclosure of Confidential Information may be required by law, regulation, or court order; in such cases the receiving party shall provide prompt written notice to the disclosing party so that the disclosing party may seek a protective order or other appropriate remedy. The receiving party shall reasonably cooperate in any such effort by the disclosing party.",
            ),
            (
                "Article II — Services",
                "Vendor shall provide the services described in one or more Statements of Work executed by the parties. Each SOW shall set forth the scope, deliverables, timeline, and fees. The Vendor shall use commercially reasonable efforts to perform the Services in a professional and workmanlike manner consistent with industry standards.",
            ),
            (
                "Article III — Fees and Payment",
                "Customer shall pay Vendor the fees set forth in each Statement of Work. Invoices shall be issued monthly and shall be due and payable within thirty (30) days of receipt. Any amounts not paid when due shall bear interest at the rate of one and one-half percent (1.5%) per month or the maximum rate permitted by law, whichever is lower.",
            ),
            (
                "Article IV — Term and Termination",
                "This Agreement shall commence on the Effective Date and shall continue for an initial term of three (3) years. Thereafter the Agreement shall automatically renew for successive one-year terms unless either party provides written notice of non-renewal at least sixty (60) days prior to the end of the then-current term. Either party may terminate this Agreement for material breach upon thirty (30) days' written notice.",
            ),
            (
                "Section 5.1 — Limitation of Liability",
                "EXCEPT FOR BREACHES OF CONFIDENTIALITY OR INDEMNIFICATION OBLIGATIONS, NEITHER PARTY'S AGGREGATE LIABILITY ARISING OUT OF OR RELATED TO THIS AGREEMENT SHALL EXCEED THE FEES PAID BY CUSTOMER TO VENDOR IN THE TWELVE (12) MONTHS PRECEDING THE EVENT GIVING RISE TO THE CLAIM. IN NO EVENT SHALL EITHER PARTY BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, OR CONSEQUENTIAL DAMAGES.",
            ),
            (
                "Section 5.2 — Indemnification",
                "Vendor shall indemnify, defend, and hold harmless Customer from any third-party claims arising out of Vendor's gross negligence or wilful misconduct, or any breach of Vendor's confidentiality obligations under Article I. Customer shall indemnify Vendor against any third-party claims arising from Customer's use of the Deliverables in violation of this Agreement.",
            ),
            (
                "Section 6.1 — Confidentiality",
                "Each party shall hold the other party's Confidential Information in strict confidence and shall not disclose such information to any third party except as expressly permitted by this Agreement. The confidentiality obligations shall survive termination of this Agreement for a period of seven (7) years.",
            ),
            (
                "Schedule A — Fee Schedule",
                "Hourly rates: Senior Partner $850/hour, Partner $625/hour, Senior Associate $425/hour, Associate $295/hour, Paralegal $165/hour. Fixed fees for routine filings available on request.",
            ),
        ],
    },
    {
        "name": "hooli_msa.pdf",
        "title": "Hooli Master Services Agreement",
        "sections": [
            (
                "Definitions",
                "Confidential Information means information disclosed by either party that is marked confidential or that a reasonable person would understand to be confidential. Force Majeure Event means any event beyond the reasonable control of the affected party.",
            ),
            (
                "Services",
                "Vendor shall perform services as set forth in each Statement of Work executed under this Agreement. Each SOW shall be governed by the terms of this Agreement.",
            ),
            (
                "Limitation of Liability",
                "Notwithstanding anything to the contrary, neither party's aggregate liability arising out of this Agreement shall exceed two times (2x) the fees paid by Customer to Vendor in the twelve (12) months preceding the event giving rise to the claim.",
            ),
            (
                "Indemnification",
                "Vendor shall indemnify Customer against third-party claims arising from Vendor's gross negligence, wilful misconduct, or breach of its confidentiality obligations. Customer shall indemnify Vendor against claims arising from Customer's misuse of the Deliverables.",
            ),
            (
                "Confidentiality",
                "Each party shall maintain the confidentiality of the other party's Confidential Information for a period of five (5) years following termination of this Agreement.",
            ),
            (
                "Fee Schedule",
                "Hourly rates: Senior Partner $950/hour, Partner $725/hour, Senior Associate $525/hour, Associate $375/hour, Paralegal $225/hour.",
            ),
        ],
    },
    # ---- expanded corpus (23 additional documents) ----
    {
        "name": "soylent_license.pdf",
        "title": "Soylent Technology License Agreement",
        "sections": [
            (
                "License Grant",
                "Licensor grants Licensee a non-exclusive, non-transferable license to use the Software solely for Licensee's internal business operations.",
            ),
            (
                "Royalties",
                "Licensee shall pay Licensor a royalty of eight percent (8%) of Net Sales of products incorporating the Licensed Technology.",
            ),
            (
                "Ownership",
                "Licensor retains all right, title, and interest in and to the Licensed Technology. Licensee acknowledges that no ownership is transferred under this Agreement.",
            ),
        ],
    },
    {
        "name": "piedpiper_license.pdf",
        "title": "Pied Piper End-User License Agreement",
        "sections": [
            (
                "License",
                "Subject to the terms of this Agreement, Company grants you a limited, non-exclusive, non-transferable license to use the Software.",
            ),
            (
                "Disclaimer of Warranties",
                "THE SOFTWARE IS PROVIDED AS IS AND AS AVAILABLE, WITHOUT WARRANTY OF ANY KIND. COMPANY DISCLAIMS ALL WARRANTIES, EXPRESS OR IMPLIED.",
            ),
        ],
    },
    {
        "name": "tyrell_license.pdf",
        "title": "Tyrell Corporation Technology License",
        "sections": [
            (
                "License Grant",
                "Tyrell grants Recipient a worldwide, royalty-bearing license to use the Patents solely for the Permitted Purpose.",
            ),
            (
                "Assignment",
                "Recipient may not assign this Agreement or any rights hereunder without Tyrell's prior written approval, which shall not be unreasonably withheld.",
            ),
            (
                "Export Control",
                "Recipient shall comply with the U.S. Export Administration Regulations (EAR) and shall not export the Licensed Technology to any prohibited destination.",
            ),
        ],
    },
    {
        "name": "vandelay_lease.pdf",
        "title": "Vandelay Industries Warehouse Lease",
        "sections": [
            (
                "Premises",
                "Lessor leases to Lessee the warehouse located at 1428 Import Way, Queens, NY.",
            ),
            (
                "Rent",
                "Lessee shall pay monthly rent of twelve thousand five hundred dollars ($12,500), due on the first day of each calendar month.",
            ),
        ],
    },
    {
        "name": "cyberdyne_lease.pdf",
        "title": "Cyberdyne Systems Office Lease",
        "sections": [
            (
                "Premises",
                "Lessor leases to Lessee the office space located at 1881 Skynet Drive, Sunnyvale, CA.",
            ),
            (
                "Security Deposit",
                "Upon execution of this Lease, Lessee shall deposit with Lessor the sum of seventy-five thousand dollars ($75,000) as security for Lessee's performance.",
            ),
            (
                "Option to Renew",
                "Lessee shall have one option to renew this Lease for an additional term of five (5) years at the then-prevailing market rate.",
            ),
        ],
    },
    {
        "name": "sterling_partnership.pdf",
        "title": "Sterling Cooper Partnership Agreement",
        "sections": [
            (
                "Profit Sharing",
                "Net profits shall be divided between the Partners as follows: sixty percent (60%) to Senior Partner; forty percent (40%) to Junior Partner.",
            ),
            (
                "Withdrawal",
                "A Partner may withdraw from the Partnership upon ninety (90) days' prior written notice to the other Partner.",
            ),
            (
                "Indemnification",
                "Each Partner shall indemnify the Partnership against any third-party claim arising from such Partner's breach of this Agreement.",
            ),
        ],
    },
    {
        "name": "massive_dynamic_sla.pdf",
        "title": "Massive Dynamic Support Services Agreement",
        "sections": [
            (
                "Service Levels",
                "Provider shall respond to Severity 1 incidents within four (4) hours of notification, twenty-four (24) hours per day.",
            ),
        ],
    },
    {
        "name": "oscorp_sla.pdf",
        "title": "Oscorp Industries Support Agreement",
        "sections": [
            (
                "Support Tiers",
                "Premium support is available 24/7 for Severity 1 issues; Standard support is provided during business hours, Monday through Friday, 9 AM to 6 PM ET.",
            ),
        ],
    },
    {
        "name": "piedpiper_employment.pdf",
        "title": "Pied Piper Engineering Employment Agreement",
        "sections": [
            (
                "Term",
                "This Agreement shall continue until either party provides sixty (60) days' written notice of non-renewal.",
            ),
            (
                "Equity Vesting",
                "Subject to continued service, twenty-five percent (25%) of the equity grant shall vest on the first anniversary of the Vesting Commencement Date, with the remainder vesting in equal monthly installments over the following three (3) years (i.e., four (4)-year vesting with a one-year cliff).",
            ),
        ],
    },
    {
        "name": "soylent_employment.pdf",
        "title": "Soylent Senior Executive Employment Agreement",
        "sections": [
            (
                "Non-Compete",
                "Employee agrees not to engage in any competitive activity for a period of twelve (12) months following termination of employment.",
            ),
        ],
    },
    {
        "name": "wonka_settlement.pdf",
        "title": "Wonka Industries Settlement and Release",
        "sections": [
            (
                "Statute of Limitations",
                "Any claim arising under this Release must be brought within two (2) years of the Effective Date, after which time it is forever barred.",
            ),
        ],
    },
    {
        "name": "cyberdyne_arbitration.pdf",
        "title": "Cyberdyne Dispute Resolution Agreement",
        "sections": [
            (
                "Arbitration Costs",
                "Each party shall bear its own costs and expenses (including attorneys' fees) of any arbitration under this Agreement.",
            ),
        ],
    },
    {
        "name": "tyrell_loi.pdf",
        "title": "Tyrell Acquisition Letter of Intent",
        "sections": [
            (
                "Break-Up Fee",
                "If the Seller accepts a Superior Proposal, the Seller shall pay the Buyer a break-up fee of five million dollars ($5,000,000) in cash.",
            ),
        ],
    },
    {
        "name": "initech_loi.pdf",
        "title": "Initech Acquisition Letter of Intent",
        "sections": [
            (
                "Exclusivity",
                "For a period of forty-five (45) days from the date hereof, Seller shall not solicit, initiate, or encourage any competing offers.",
            ),
        ],
    },
    {
        "name": "massive_dynamic_jv.pdf",
        "title": "Massive Dynamic Joint Venture Agreement",
        "sections": [
            (
                "Background IP",
                "Each Party shall retain ownership of its Background IP. Neither Party grants the other any license to its Background IP except as expressly set forth herein.",
            ),
        ],
    },
    {
        "name": "globex_wayne_jv.pdf",
        "title": "Globex-Wayne Joint Venture Agreement",
        "sections": [
            (
                "Revenue Allocation",
                "Revenue from Joint Venture Activities shall be allocated equally: fifty percent (50%) to Globex; fifty percent (50%) to Wayne.",
            ),
        ],
    },
    {
        "name": "cyberdyne_dpa.pdf",
        "title": "Cyberdyne Data Processing Addendum",
        "sections": [
            (
                "Breach Notification",
                "Processor shall notify Controller of any Personal Data breach within seventy-two (72) hours of becoming aware of it.",
            ),
        ],
    },
    {
        "name": "hooli_dpa.pdf",
        "title": "Hooli Data Processing Addendum",
        "sections": [
            (
                "Data Return and Deletion",
                "Upon termination, Processor shall delete all Personal Data within thirty (30) days and certify deletion in writing.",
            ),
        ],
    },
    {
        "name": "massive_dynamic_dpa.pdf",
        "title": "Massive Dynamic Data Processing Addendum",
        "sections": [
            (
                "Data Subject Rights",
                "Processor shall assist Controller in fulfilling Data Subject rights requests, including access, rectification, erasure, and portability.",
            ),
        ],
    },
    {
        "name": "soylent_msa_reg.pdf",
        "title": "Soylent Master Services Agreement (Regulated)",
        "sections": [
            (
                "Change in Law",
                "If a Change in Law materially affects either party's performance, the parties shall negotiate in good faith an equitable adjustment to the affected terms.",
            ),
        ],
    },
    {
        "name": "piedpiper_insurance.pdf",
        "title": "Pied Piper Insurance Schedule",
        "sections": [
            (
                "Cyber Liability",
                "The Insured shall maintain cyber liability coverage of not less than ten million dollars ($10,000,000) per occurrence.",
            ),
        ],
    },
    {
        "name": "oscorp_insurance.pdf",
        "title": "Oscorp Insurance Schedule",
        "sections": [
            (
                "Professional Liability Deductible",
                "The deductible for the professional liability policy shall be fifty thousand dollars ($50,000) per claim.",
            ),
        ],
    },
    {
        "name": "tyrell_supply.pdf",
        "title": "Tyrell Components Supply Agreement",
        "sections": [
            (
                "Warranty",
                "Supplier warrants the Products for a period of twenty-four (24) months from the date of delivery against defects in materials and workmanship.",
            ),
        ],
    },
    {
        "name": "soylent_supply.pdf",
        "title": "Soylent Ingredients Supply Agreement",
        "sections": [
            (
                "Minimum Order Quantity",
                "Buyer's minimum order quantity shall be ten thousand units (10,000 units) per order, with monthly minimum commitments.",
            ),
        ],
    },
    {
        "name": "vandelay_marketing.pdf",
        "title": "Vandelay Co-Marketing Agreement",
        "sections": [
            (
                "Brand Approval",
                "All co-branded materials shall be submitted for approval; the receiving party shall respond within ten (10) business days.",
            ),
        ],
    },
    {
        "name": "piedpiper_marketing.pdf",
        "title": "Pied Piper Co-Marketing Agreement",
        "sections": [
            (
                "Revenue Share",
                "Co-marketing revenue shall be allocated: seventy percent (70%) to Pied Piper; thirty percent (30%) to the Partner.",
            ),
        ],
    },
    {
        "name": "initech_msa.pdf",
        "title": "Initech Master Services Agreement",
        "sections": [
            (
                "Limitation of Liability",
                "Neither party's aggregate liability under this Agreement shall exceed two times (2x) the fees paid in the twelve (12) months preceding the claim.",
            ),
            (
                "Indemnification",
                "Vendor shall indemnify Customer against claims arising from Vendor's negligence or breach of confidentiality.",
            ),
        ],
    },
    {
        "name": "stark_bonus.pdf",
        "title": "Stark Industries Executive Bonus Plan",
        "sections": [
            (
                "Bonus Pool",
                "The annual bonus pool shall be twenty-five million dollars ($25,000,000), allocated to executives based on Company and individual performance.",
            ),
        ],
    },
    {
        "name": "tyrell_retention.pdf",
        "title": "Tyrell Key Employee Retention Agreement",
        "sections": [
            (
                "Retention Bonus",
                "Employee shall receive a retention bonus of two hundred thousand dollars ($200,000), payable in equal installments over eighteen months of continued service.",
            ),
        ],
    },
    {
        "name": "wayne_ibm_supply.pdf",
        "title": "Wayne-IBM Supplier Agreement",
        "sections": [
            (
                "Audit Rights",
                "Wayne may audit IBM's records once per year, upon reasonable notice, to verify compliance with this Agreement.",
            ),
        ],
    },
]


FIXTURE = {
    "cases": [
        # basic needle questions
        {
            "question": "What's the cap on liability?",
            "expected_source": "globex_msa",
            "expected_keywords": ["twelve (12) months", "fees paid"],
        },
        {
            "question": "How long does the NDA last?",
            "expected_source": "initech_nda",
            "expected_keywords": ["three (3) years", "five (5) years"],
        },
        {
            "question": "What's the settlement amount?",
            "expected_source": "umbrella_settlement",
            "expected_keywords": ["$2,400,000", "thirty (30) days"],
        },
        {
            "question": "What is the CEO's severance?",
            "expected_source": "wayne_employment",
            "expected_keywords": ["twenty-four (24) months", "Base Salary"],
        },
        {
            "question": "What is the audit fee cap?",
            "expected_source": "stark_audit",
            "expected_keywords": ["$450,000", "out-of-pocket expenses"],
        },
        {
            "question": "What are the Partner hourly rates?",
            "expected_source": "globex_msa",
            "expected_keywords": ["$550", "$750"],
        },
        {
            "question": "What's the severance period for the CEO?",
            "expected_source": "wayne_employment",
            "expected_keywords": ["twenty-four (24) months"],
        },
        {
            "question": "What's the NDA governing law?",
            "expected_source": "initech_nda",
            "expected_keywords": ["Delaware"],
        },
        {
            "question": "What is the bonus target?",
            "expected_source": "wayne_employment",
            "expected_keywords": ["two hundred percent", "200%"],
        },
        {
            "question": "What's the mutual release clause?",
            "expected_source": "umbrella_settlement",
            "expected_keywords": ["Settlement Amount", "Effective Date"],
        },
        # adversarial: same keyword in multiple docs
        {
            "question": "What is the limitation of liability in the Acme long-form MSA?",
            "expected_source": "acme_msa_long",
            "expected_keywords": ["twelve (12) months", "fees paid", "Customer"],
        },
        {
            "question": "What is the limitation of liability in the Hooli MSA?",
            "expected_source": "hooli_msa",
            "expected_keywords": ["two times", "2x"],
        },
        {
            "question": "How long are confidentiality obligations in the Acme long-form MSA?",
            "expected_source": "acme_msa_long",
            "expected_keywords": ["seven (7) years"],
        },
        {
            "question": "What is the audit reportable condition clause?",
            "expected_source": "stark_audit",
            "expected_keywords": ["Reportable Conditions", "Audit Committee"],
        },
        {
            "question": "What are the Senior Partner hourly rates in the Acme MSA?",
            "expected_source": "acme_msa_long",
            "expected_keywords": ["$850"],
        },
        {
            "question": "What is the Force Majeure definition in the Globex MSA?",
            "expected_source": "globex_msa",
            "expected_keywords": ["Force Majeure", "acts of God"],
        },
        # borderline: cross-document, hard to disambiguate
        {
            "question": "What's the confidentiality survival period after termination?",
            "expected_source": "acme_msa_long",
            "expected_keywords": ["seven (7) years", "survive"],
        },
        {
            "question": "What's the NDA's confidentiality survival?",
            "expected_source": "initech_nda",
            "expected_keywords": ["five (5) years"],
        },
        {
            "question": "What's the late payment interest rate?",
            "expected_source": "acme_msa_long",
            "expected_keywords": ["one and one-half percent", "1.5%"],
        },
        {
            "question": "What is the auto-renewal notice period?",
            "expected_source": "acme_msa_long",
            "expected_keywords": ["sixty (60) days"],
        },
        # ---- additional categories ----
        # IP / licensing
        {
            "question": "What is the royalty rate in the Soylent licensing agreement?",
            "expected_source": "soylent_license",
            "expected_keywords": ["8%", "Net Sales"],
        },
        {
            "question": "Who owns the intellectual property in the Soylent license?",
            "expected_source": "soylent_license",
            "expected_keywords": ["Licensor", "retains"],
        },
        {
            "question": "What is the warranty disclaimer in the Pied Piper license?",
            "expected_source": "piedpiper_license",
            "expected_keywords": ["AS IS", "disclaimer"],
        },
        {
            "question": "Can the Tyrell license be assigned to a third party?",
            "expected_source": "tyrell_license",
            "expected_keywords": ["consent", "written approval"],
        },
        # real estate
        {
            "question": "What is the monthly rent for the Vandelay warehouse lease?",
            "expected_source": "vandelay_lease",
            "expected_keywords": ["$12,500", "month"],
        },
        {
            "question": "What is the security deposit for the Cyberdyne office lease?",
            "expected_source": "cyberdyne_lease",
            "expected_keywords": ["$75,000"],
        },
        # partnerships
        {
            "question": "What is the profit split in the Sterling Cooper partnership?",
            "expected_source": "sterling_partnership",
            "expected_keywords": ["60%", "40%"],
        },
        {
            "question": "What are the partner withdrawal rights?",
            "expected_source": "sterling_partnership",
            "expected_keywords": ["ninety (90) days", "written notice"],
        },
        # service agreements (more)
        {
            "question": "What is the response time SLA in the Massive Dynamic support agreement?",
            "expected_source": "massive_dynamic_sla",
            "expected_keywords": ["four (4) hours", "Severity 1"],
        },
        {
            "question": "What are the support tier hours in the Oscorp agreement?",
            "expected_source": "oscorp_sla",
            "expected_keywords": ["24/7", "business hours"],
        },
        # employment (more)
        {
            "question": "What is the notice period for non-renewal in the Pied Piper employment agreement?",
            "expected_source": "piedpiper_employment",
            "expected_keywords": ["sixty (60) days"],
        },
        {
            "question": "What is the non-compete duration in the Soylent employment agreement?",
            "expected_source": "soylent_employment",
            "expected_keywords": ["twelve (12) months"],
        },
        {
            "question": "What is the equity vesting schedule in the Pied Piper employment agreement?",
            "expected_source": "piedpiper_employment",
            "expected_keywords": ["four (4) years", "cliff"],
        },
        # litigation / settlement
        {
            "question": "What is the statute of limitations in the Wonka settlement release?",
            "expected_source": "wonka_settlement",
            "expected_keywords": ["two (2) years"],
        },
        {
            "question": "Who pays the arbitration costs in the Cyberdyne dispute resolution agreement?",
            "expected_source": "cyberdyne_arbitration",
            "expected_keywords": ["each party", "own costs"],
        },
        # M&A / LOI
        {
            "question": "What is the break-up fee in the Tyrell acquisition LOI?",
            "expected_source": "tyrell_loi",
            "expected_keywords": ["$5,000,000"],
        },
        {
            "question": "What is the exclusivity period in the Initech LOI?",
            "expected_source": "initech_loi",
            "expected_keywords": ["forty-five (45) days"],
        },
        # IP & trade
        {
            "question": "Who owns pre-existing IP in the Massive Dynamic joint venture?",
            "expected_source": "massive_dynamic_jv",
            "expected_keywords": ["Background IP", "own"],
        },
        {
            "question": "What is the revenue share in the Globex-Wayne joint venture?",
            "expected_source": "globex_wayne_jv",
            "expected_keywords": ["50%", "50%"],
        },
        # real estate (more)
        {
            "question": "What is the option-to-renew term for the Cyberdyne lease?",
            "expected_source": "cyberdyne_lease",
            "expected_keywords": ["five (5) years"],
        },
        # harder disambiguation
        {
            "question": "What is the Force Majeure definition in the Acme MSA?",
            "expected_source": "acme_msa_long",
            "expected_keywords": ["beyond", "reasonable control"],
        },
        {
            "question": "What is the audit reportable condition notification timeline?",
            "expected_source": "stark_audit",
            "expected_keywords": ["promptly", "during the engagement"],
        },
        # privacy / data
        {
            "question": "What is the data breach notification timeline in the Cyberdyne DPA?",
            "expected_source": "cyberdyne_dpa",
            "expected_keywords": ["seventy-two (72) hours"],
        },
        {
            "question": "What is the data retention period in the Hooli DPA?",
            "expected_source": "hooli_dpa",
            "expected_keywords": ["thirty (30) days", "termination"],
        },
        {
            "question": "What is the GDPR data subject rights clause in the Massive Dynamic DPA?",
            "expected_source": "massive_dynamic_dpa",
            "expected_keywords": ["Data Subject", "rights"],
        },
        # regulatory
        {
            "question": "What is the regulatory change clause in the Soylent MSA?",
            "expected_source": "soylent_msa_reg",
            "expected_keywords": ["Change in Law", "equitable adjustment"],
        },
        {
            "question": "What is the export control clause in the Tyrell technology license?",
            "expected_source": "tyrell_license",
            "expected_keywords": ["Export Administration", "EAR"],
        },
        # insurance
        {
            "question": "What is the cyber liability coverage amount in the Pied Piper insurance schedule?",
            "expected_source": "piedpiper_insurance",
            "expected_keywords": ["$10,000,000"],
        },
        {
            "question": "What is the deductible for the professional liability policy in the Oscorp insurance schedule?",
            "expected_source": "oscorp_insurance",
            "expected_keywords": ["$50,000", "deductible"],
        },
        # supply / manufacturing
        {
            "question": "What is the warranty period for the Tyrell supply agreement?",
            "expected_source": "tyrell_supply",
            "expected_keywords": ["twenty-four (24) months"],
        },
        {
            "question": "What is the minimum order quantity in the Soylent supply agreement?",
            "expected_source": "soylent_supply",
            "expected_keywords": ["10,000 units"],
        },
        # marketing / brand
        {
            "question": "What is the brand approval timeline in the Vandelay co-marketing agreement?",
            "expected_source": "vandelay_marketing",
            "expected_keywords": ["ten (10) business days"],
        },
        {
            "question": "What is the revenue share in the Pied Piper co-marketing agreement?",
            "expected_source": "piedpiper_marketing",
            "expected_keywords": ["70%", "30%"],
        },
        # hard cross-document disambiguation
        {
            "question": "What's the cap on liability in any Initech agreement?",
            "expected_source": "initech_msa",
            "expected_keywords": ["two times (2x)", "fees paid"],
        },
        {
            "question": "What's the indemnification scope in the Sterling Cooper partnership?",
            "expected_source": "sterling_partnership",
            "expected_keywords": ["breach", "third-party claim"],
        },
        # adversarial: very similar topics across firms
        {
            "question": "What is the bonus pool in the Stark Industries executive bonus plan?",
            "expected_source": "stark_bonus",
            "expected_keywords": ["$25,000,000", "annual"],
        },
        {
            "question": "What is the retention bonus in the Tyrell retention agreement?",
            "expected_source": "tyrell_retention",
            "expected_keywords": ["$200,000", "eighteen months"],
        },
        # multi-clause
        {
            "question": "What are the termination notice and cure provisions across the firm's contracts?",
            "expected_source": "globex_msa",
            "expected_keywords": ["thirty (30) days", "uncured"],
        },
        {
            "question": "What is the audit and inspection right in the Wayne-IBM supplier agreement?",
            "expected_source": "wayne_ibm_supply",
            "expected_keywords": ["once per year", "reasonable notice"],
        },
    ]
}


def main() -> int:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "eval/compare_corpus")
    out_dir.mkdir(parents=True, exist_ok=True)
    for c in CORPUS:
        sections: list[tuple[str, str]] = [(s[0], s[1]) for s in c["sections"]]
        title: str = c["title"]
        build_pdf(out_dir / c["name"], title, sections)
    Path("eval/compare_fixture.json").write_text(json.dumps(FIXTURE, indent=2))
    print(
        json.dumps(
            {"corpus": [c["name"] for c in CORPUS], "cases": len(FIXTURE["cases"])}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
