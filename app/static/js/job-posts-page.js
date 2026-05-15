import { authFetch, showMkToast } from "/static/js/main.js";

const jobList = document.getElementById("jobList");
const newJobBtn = document.getElementById("newJobBtn");
const jobModal = document.getElementById("jobModal");
const jobForm = document.getElementById("jobForm");
const closeModalBtns = document.querySelectorAll(".close-modal");

async function fetchMyJobs() {
    try {
        const res = await authFetch("/api/jobs/mine");
        if (!res.ok) throw new Error("Failed to fetch jobs");
        const jobs = res.data;
        renderJobs(jobs);
    } catch (err) {
        console.error("Failed to fetch jobs:", err);
        jobList.innerHTML = `<div class="mk-card" style="text-align:center;padding:40px;"><p class="mk-body-sm" style="color:var(--danger-600);">Failed to load jobs. Please refresh the page.</p></div>`;
    }
}

function renderJobs(jobs) {
    if (!jobs || jobs.length === 0) {
        jobList.innerHTML = `
            <div class="mk-card mk-empty-state" style="padding: 40px; text-align: center; border-style: dashed; max-width: 100%;">
                <i data-lucide="briefcase" style="width:48px;height:48px;color:var(--gray-300);margin-bottom:16px;"></i>
                <p class="mk-body-sm" style="color: var(--gray-500); margin-bottom: 16px;">You haven't posted any jobs yet.</p>
                <button class="btn secondary" onclick="document.getElementById('newJobBtn').click()">Post your first job</button>
            </div>
        `;
        if (window.lucide) window.lucide.createIcons();
        return;
    }

    jobList.innerHTML = jobs.map(job => `
        <div class="mk-card mk-stagger-child" style="padding: 20px;">
            <div style="display:flex; justify-content:space-between; align-items:start; flex-wrap:wrap; gap:16px;">
                <div>
                    <h3 class="mk-heading" style="margin-bottom:4px;">${escapeHtml(job.title)}</h3>
                    <p class="mk-body-sm muted" style="margin-bottom:12px;">Posted on ${new Date(job.created_at).toLocaleDateString()}</p>
                    <div class="badge-row">
                        <span class="chip" data-state="${job.status.toLowerCase()}">${job.status}</span>
                        <span class="chip" style="background:var(--brand-50); color:var(--brand-700);">
                            <i data-lucide="users" style="width:14px;height:14px;"></i>
                            ${job.proposal_count} proposals
                        </span>
                    </div>
                </div>
                <div class="actions">
                    <a href="/jobs/${job.id}" class="btn ghost">
                        View Details
                        <i data-lucide="chevron-right" style="width:16px;height:16px;"></i>
                    </a>
                </div>
            </div>
        </div>
    `).join("");
    
    if (window.lucide) window.lucide.createIcons();
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

if (newJobBtn) {
    newJobBtn.addEventListener("click", () => {
        jobModal.style.display = "flex";
    });
}

closeModalBtns.forEach(btn => {
    btn.addEventListener("click", () => {
        jobModal.style.display = "none";
    });
});

window.addEventListener("click", (e) => {
    if (e.target === jobModal) {
        jobModal.style.display = "none";
    }
});

if (jobForm) {
    jobForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const submitBtn = document.getElementById("submitJobBtn");
        submitBtn.disabled = true;
        const originalText = submitBtn.textContent;
        submitBtn.textContent = "Posting...";

        const data = {
            title: document.getElementById("jobTitle").value,
            description: document.getElementById("jobDescription").value,
            budget_min: document.getElementById("budgetMin").value || null,
            budget_max: document.getElementById("budgetMax").value || null,
            location_text: document.getElementById("locationText").value,
        };

        try {
            const res = await authFetch("/api/jobs", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(data)
            });

            if (res.ok) {
                showMkToast("Job posted successfully!", "success");
                jobModal.style.display = "none";
                jobForm.reset();
                fetchMyJobs();
            } else {
                showMkToast(res.data?.error || "Failed to post job", "error");
            }
        } catch (err) {
            showMkToast("An error occurred. Please try again.", "error");
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = originalText;
        }
    });
}

fetchMyJobs();
