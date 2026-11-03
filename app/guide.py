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
