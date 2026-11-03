"""Extra details for startup and research projects, and where to take them next.
Facts checked in November 2026. Programs change every year, so the page always tells students to read the official call."""

STARTUP_CATEGORIES = ["AI & software", "Education", "Health & biotech", "Fintech", "Climate & energy", "Hardware & IoT",
                      "Consumer & e-commerce", "Social impact", "Media & creative", "Food & agriculture", "Mobility & logistics", "Other"]

STARTUP_STAGES = [("Idea", "A problem you care about, no product yet"),
                  ("Prototype", "Something people can try"),
                  ("Early users", "Real people use it"),
                  ("Revenue", "People pay for it")]

NTHU_OCIC = ("NTHU Operations Center for Industry Collaboration", "https://ocic.nthu.edu.tw/",
             "NTHU's industry and incubation office. It coaches cross-faculty teams that turn research into startups, "
             "and it is the school office a U-start application goes through. Ask them about incubation and coaching.")
USTART = ("U-start Innovation & Startup Program (Ministry of Education)", "https://www.yda.gov.tw/",
          "Startup grant for student teams: at least 3 members, at least two thirds of them current students or graduates "
          "of the last 5 school years. You apply through a university incubator such as NTHU's. "
          "Stage 1 calls usually open around January to February.")
FITI = ("FITI Innovation & Startup Incentive Program (NSTC / NIAR)", "https://iic.npust.edu.tw/wp-content/uploads/2026/06/FITI-2026-2-%E5%BE%B5%E4%BB%B6%E8%AA%AA%E6%98%8E.pdf",
        "For tech and health-care teams with university students or recent graduates. Six months of training; "
        "teams that reach the final can win a NT$1,000,000 startup fund. It runs about two calls a year "
        "(the second 2026 call closed on 24 June 2026), so watch for the next one.")

STAGE_STEPS = {
    "Idea": ["Talk to at least 10 people who have the problem, and write down what they say.",
             "Enter a business plan or social-impact competition from the list on the home page to get feedback.",
             "Book a first talk with NTHU's incubation office about coaching."],
    "Prototype": ["Put the prototype in front of 10 to 20 real users and measure one number that matters.",
                  "Prepare a U-start application with NTHU's incubation office; you need at least 3 members.",
                  "If it is a tech or health product, check the next FITI call."],
    "Early users": ["Track how many users come back each week; that is what grant reviewers and investors ask first.",
                    "Apply for U-start or FITI with your user numbers.",
                    "Ask NTHU's incubation office about joining the incubator and meeting angel investors."],
    "Revenue": ["Register the company if you have not; U-start stage 2 requires a registered company.",
                "Ask NTHU's incubation office about incubator space and introductions to seed investors.",
                "Keep a simple record of monthly revenue and costs; seed investors will ask for it."],
}

# Research: well-known, free places to share or publish, by field
RESEARCH_VENUES = {
    "Computer science & AI": [("arXiv (cs)", "https://arxiv.org/", "The standard free preprint server for computer science and AI papers."),
                              ("GitHub + Zenodo", "https://zenodo.org/", "Publish your code and data with a citable DOI."),
                              ("Top conferences", "https://www.acm.org/conferences", "Aim for a workshop or student track at ACM or IEEE conferences in your area.")],
    "Electrical engineering": [("arXiv (eess)", "https://arxiv.org/", "Preprints for signal processing, systems and electrical engineering."),
                               ("IEEE conferences", "https://conferences.ieee.org/", "Most EE papers appear at IEEE conferences; many have student paper tracks.")],
    "Physics & math": [("arXiv", "https://arxiv.org/", "Physics and math researchers post almost every paper here first.")],
    "Chemistry & materials": [("ChemRxiv", "https://chemrxiv.org/", "The main free preprint server for chemistry and materials science.")],
    "Biology & life science": [("bioRxiv", "https://www.biorxiv.org/", "The main preprint server for biology."),
                               ("PLOS ONE", "https://journals.plos.org/plosone/", "Open-access journal that judges soundness, not novelty.")],
    "Medicine & health": [("medRxiv", "https://www.medrxiv.org/", "Preprints for medicine and public health. Studies on people need ethics approval first.")],
    "Earth & environment": [("EarthArXiv", "https://eartharxiv.org/", "Free preprints for earth, climate and environmental science."),
                            ("Zenodo", "https://zenodo.org/", "Publish sensor data or maps with a citable DOI.")],
    "Economics, business & finance": [("SSRN", "https://www.ssrn.com/", "Where economics, finance and management working papers are shared.")],
    "Psychology & education": [("PsyArXiv / EdArXiv (OSF)", "https://osf.io/preprints/", "Preprints for psychology and education research."),
                               ("OSF preregistration", "https://osf.io/", "Register your study plan before collecting data; reviewers trust it more.")],
    "Social science & policy": [("SocArXiv (OSF)", "https://osf.io/preprints/socarxiv", "Preprints for sociology, political science and policy."),
                                ("SSRN", "https://www.ssrn.com/", "Widely read for law and policy papers.")],
    "Law": [("SSRN Legal Scholarship Network", "https://www.ssrn.com/", "Most law working papers are shared here.")],
    "Humanities & arts": [("Humanities Commons", "https://hcommons.org/", "Open repository for humanities papers, essays and projects.")],
    "Design & HCI": [("ACM CHI student research", "https://chi2026.acm.org/", "The main human-computer interaction conference; it has a student research track."),
                     ("Behance", "https://www.behance.net/", "Show the design work itself alongside any paper.")],
    "Other": [("OSF Preprints", "https://osf.io/preprints/", "A general home for preprints in any field."),
              ("Zenodo", "https://zenodo.org/", "Publish anything with a citable DOI: data, code, posters, reports.")],
}
RESEARCH_FIELDS = list(RESEARCH_VENUES)

NSTC_GRANT = ("NSTC Undergraduate Research Grant (大專學生研究計畫)", "https://www.nstc.gov.tw/",
              "For undergraduates in year 2 or above with a professor as advisor: NT$6,000 a month for 8 months (July to February), "
              "plus up to NT$20,000 for materials. Applications are usually due in February through your school's research office.")

# ---------- funding and incubation programs (seeded once into the Program table; admins edit dates later) ----------
TECH_HEALTH = "AI & software,Health & biotech,Hardware & IoT,Climate & energy,Fintech,Mobility & logistics"
PROGRAMS = [
    dict(key="nthu-ocic", sort=1, for_kind="Startup", name="NTHU incubation office (OCIC)", org="National Tsing Hua University",
         url="https://ocic.nthu.edu.tw/", amount="Coaching, incubator support and introductions",
         who="NTHU students and cross-faculty teams turning an idea or research into a startup.",
         deadline_note="Open all year: contact them any time.",
         self_checks="Email or visit the office with a short summary of your idea"),
    dict(key="ustart", sort=2, for_kind="Startup", name="U-start Innovation & Startup Program", org="Ministry of Education (Youth Development Administration)",
         url="https://www.yda.gov.tw/", amount="About NT$500,000 in stage 1; strong teams with a registered company can get more in stage 2",
         who="Teams of 3 or more; at least two thirds current students or graduates of the last 5 school years.",
         deadline_note="Calls usually open around January to February. The date is added here once announced.",
         min_members=3, self_checks="Apply through NTHU's incubation office, before the school's own internal deadline|One school per team"),
    dict(key="fiti", sort=3, for_kind="Startup", name="FITI Innovation & Startup Incentive Program", org="NSTC / NIAR",
         url="https://iic.npust.edu.tw/wp-content/uploads/2026/06/FITI-2026-2-%E5%BE%B5%E4%BB%B6%E8%AA%AA%E6%98%8E.pdf",
         amount="Staged awards; finalists can win a NT$1,000,000 startup fund",
         who="Tech and health-care teams with university students or graduates of the past year; outsiders at most half the team.",
         deadline_note="About two calls a year; the last one closed on 24 June 2026.",
         categories=TECH_HEALTH, self_checks="Team members are students or graduated within the past year"),
    dict(key="appworks", sort=5, for_kind="Startup", name="AppWorks Accelerator", org="AppWorks (Taipei)",
         url="https://appworks.tw/accelerator", amount="6 months of mentoring and a founder network; free, takes no equity and charges no fees",
         who="Founders from first prototype to scaling; Taiwan and the rest of Asia. Each batch also names focus areas.",
         deadline_note="New batch every 6 months. AW#34 applications run October to December 2026 (kick-off March 2027).",
         self_checks="At least one founder can commit to the 6-month program"),
    dict(key="youth-loan", sort=6, for_kind="Startup", name="Youth Startup Loan (青年創業貸款)", org="Ministry of Economic Affairs, SME and Startup Administration",
         url="https://www.sme.gov.tw/", amount="Low-interest loan: up to NT$6 million for working capital and NT$12 million for equipment and other capital costs",
         who="Founders aged 18 to 45 with a registered business. Foreign founders need an entrepreneur visa, Gold Card or valid residence permit.",
         deadline_note="Open all year through banks. It is a loan, not a grant: it has to be paid back.",
         self_checks="The person in charge is 18 to 45|The business is registered (company, firm or partnership)|At least 20 hours of approved startup training in the last 3 years"),
    dict(key="nstc", sort=4, for_kind="Research", name="NSTC Undergraduate Research Grant (大專學生研究計畫)", org="National Science and Technology Council",
         url="https://www.nstc.gov.tw/", amount="NT$6,000 a month for 8 months, plus up to NT$20,000 for materials",
         who="Undergraduates in year 2 or above, with an NTHU professor as advisor.",
         deadline_note="Usually due in February through the school's research office.",
         needs_advisor=True, self_checks="The main applicant is in year 2 or above|Your advisor agrees to supervise the project"),
    dict(key="sinica-summer", sort=7, for_kind="Research", name="Academia Sinica summer student programs (中研院暑期大專生研習)", org="Academia Sinica",
         url="https://www.sinica.edu.tw/", amount="A summer working in an Academia Sinica research lab",
         who="Undergraduates; each institute (physics, chemistry, IT, humanities and more) runs its own program and rules.",
         deadline_note="Most institutes take applications around March to April (Physics 2026: 13 March to 22 April).",
         self_checks="Check the rules of the institute you want; foreign-student rules differ"),
    dict(key="macronix", sort=8, for_kind="Research", name="Macronix Golden Silicon Awards (旺宏金矽獎)", org="Macronix Education Foundation",
         url="https://www.mxeduc.org.tw/SiliconAwards", amount="Scholarship prizes; a single team won NT$700,000 in 2026",
         who="Student teams from Taiwan universities with semiconductor or AI application projects (Design and Application groups).",
         deadline_note="Runs once a year; see the official site for the next call.",
         categories="Electrical engineering,Computer science & AI,Physics & math,Chemistry & materials",
         self_checks="The project uses semiconductor chips or designs them"),
]

def readiness(prog, pr, members, students, advisors):
    """Check a project against one program. Returns a list of (state, text, fix); state is ok / miss / you."""
    out = []
    if prog.min_members:
        out.append(("ok" if members >= prog.min_members else "miss", f"Team has {members} of at least {prog.min_members} members", "seat"))
        out.append(("ok" if students * 3 >= members * 2 else "miss", f"{students} of {members} members are students (at least two thirds needed)", ""))
    if prog.needs_advisor:
        out.append(("ok" if advisors else "miss", "Has a professor as advisor" if advisors else "No advisor yet", "advisor"))
    if prog.categories:
        fits = pr.category in prog.categories.split(",")
        out.append(("ok" if fits else "you", f"Category fits ({pr.category})" if fits else "Check that your project's field fits this program", "category" if not pr.category else ""))
    for c in filter(None, prog.self_checks.split("|")): out.append(("you", c, ""))
    return out
