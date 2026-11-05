# Data schema

## stg_jobs

One cleaned row per job posting.

| Column | Type | Meaning | Example |
|---|---|---|---|
| `job_id` | text | Identifier of the job posting, taken from the source posting. | 2091101, 2091100, 2091099 |
| `title` | text | Job title. | Senior React Full-stack Developer, Senior QA Engineer, Senior DevOps Engineer |
| `company_name` | text | Name of the company advertising the job. | Lemon.io, Lemon.io, Lemon.io |
| `category` | text | Source category assigned to the job posting. | Software Development, Quality Assurance, Devops |
| `tags` | jsonb | Tags supplied with the source job posting. | [".Net", "android", "AWS", "backend", "C", "C#", "C++", "data science", "fullstack", "golang", "i..., [".Net", "android", "C", "C#", "C++", "data science", "golang", "ios", "java", "javascript", "nod..., [".Net", "android", "AWS", "azure", "C", "C#", "C++", "data science", "golang", "heroku", "ios", ... |
| `salary` | text | Salary text supplied with the source job posting. | No sample value |
| `url` | text | Link to the original job posting. | https://remotive.com/remote-jobs/software-development/senior-react-full-stack-developer-2091101, https://remotive.com/remote-jobs/qa/senior-qa-engineer-2091100, https://remotive.com/remote-jobs/devops/senior-devops-engineer-2091099 |
| `publication_date` | timestamp with time zone | Date and time the job posting was published. | 2026-08-27 14:36:09-07:00, 2026-08-26 13:10:58-07:00, 2026-08-25 13:57:53-07:00 |
| `description` | text | Description text from the job posting. | <p>Are you a talented Senior Developer looking for a remote job that lets you show your skills an..., <p>Are you a talented QA looking for a remote job that lets you show your skills and get better c..., <p>Are you a talented Senior DevOps looking for a remote job that lets you show your skills and g... |

Sample rows available: 3.

## job_skills

One row for each recognized skill mentioned in a job posting.

| Column | Type | Meaning | Example |
|---|---|---|---|
| `job_id` | text | Identifier of the job posting, taken from the source posting. | 1680495, 1680495, 1919265 |
| `skill` | text | Recognized skill name, such as Python or SQL. | Git, PHP, Go |

Sample rows available: 3.

## skill_trends

Daily posting counts for each recognized skill.

| Column | Type | Meaning | Example |
|---|---|---|---|
| `publication_date` | date | Date and time the job posting was published. | 2026-08-19, 2026-08-25, 2026-09-05 |
| `skill` | text | Recognized skill name, such as Python or SQL. | Vue, PHP, JavaScript |
| `job_posting_count` | bigint | Number of postings for this skill on this publication date. | 4, 4, 1 |

Sample rows available: 3.
