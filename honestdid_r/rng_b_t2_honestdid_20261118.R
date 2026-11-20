# HonestDiD relative-magnitude intervals on the screened six-year window.
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 4L)
library_path <- args[[1L]]
input_path <- args[[2L]]
outcome <- args[[3L]]
output <- args[[4L]]
stopifnot(outcome %in% c("concentration_pp", "log_recovery"), dir.exists(output))
.libPaths(c(library_path, .libPaths()))
suppressPackageStartupMessages(library(HonestDiD))
stopifnot(as.character(packageVersion("HonestDiD")) == "0.2.8")
started <- Sys.time()
seed <- 17261117L
grid_points <- 1000L
target_weights <- c(0, 0.5, 0.5)
events <- c(-3, -2, 0, 1, 2)
data <- read.csv(input_path, stringsAsFactors = FALSE)
data <- data[data$outcome == outcome, ]
beta <- data[data$kind == "beta", ]
covariance <- data[data$kind == "covariance", ]
stopifnot(identical(as.numeric(beta$row_event), events))
stopifnot(identical(as.numeric(covariance$row_event), rep(events, each = 5)))
stopifnot(identical(as.numeric(covariance$column_event), rep(events, 5)))
sigma <- matrix(covariance$value, nrow = 5L, byrow = TRUE)
stopifnot(isSymmetric(sigma, tol = 1e-12))
smallest_eigenvalue <- min(eigen(sigma, symmetric = TRUE, only.values = TRUE)$values)
stopifnot(is.finite(smallest_eigenvalue), smallest_eigenvalue > 0)
ci_path <- file.path(output, "sensitivity.csv")
state_path <- file.path(output, "breakdown.csv")
meta_path <- file.path(output, "R_RECEIPT.csv")
stopifnot(!any(file.exists(c(ci_path, state_path, meta_path))))

spans_zero <- function(x) x$lb <= 0 & x$ub >= 0

estimate_grid <- function(grid, stage) {
    cat(outcome, stage, paste(grid, collapse = ","), "\n")
    flush.console()
    intervals <- as.data.frame(
        createSensitivityResults_relativeMagnitudes(
            betahat = beta$value, sigma = sigma,
            numPrePeriods = 2L, numPostPeriods = 3L, l_vec = target_weights,
            method = "C-LF", Mbarvec = grid, alpha = 0.05,
            gridPoints = grid_points, parallel = FALSE, seed = seed
        )
    )
    stopifnot(nrow(intervals) == length(grid), setequal(intervals$Mbar, grid))
    stopifnot(all(is.finite(intervals$lb)), all(is.finite(intervals$ub)), all(intervals$lb <= intervals$ub))
    intervals$outcome <- outcome
    intervals$stage <- stage
    intervals$includes_zero <- spans_zero(intervals)
    intervals$reported_lb <- if (outcome == "concentration_pp") intervals$lb else 100 * expm1(intervals$lb)
    intervals$reported_ub <- if (outcome == "concentration_pp") intervals$ub else 100 * expm1(intervals$ub)
    intervals
}

save_intervals <- function(intervals) {
    write.csv(intervals[order(intervals$Mbar), ], ci_path, row.names = FALSE)
}

ci <- estimate_grid(c(0, .25, .5, .75, 1), "prespecified_grid")
save_intervals(ci)
for (value in c(1.5, 2, 3, 4)) {
    if (any(ci$includes_zero)) break
    ci <- rbind(ci, estimate_grid(value, "extended_grid"))
    save_intervals(ci)
}
status <- "above_tested_grid"
lower <- max(ci$Mbar)
upper <- NA_real_
if (any(ci$includes_zero)) {
    upper <- min(ci$Mbar[ci$includes_zero])
    if (upper == 0) {
        lower <- 0
        status <- "includes_zero_at_zero"
    } else {
        lower <- max(ci$Mbar[ci$Mbar < upper])
        status <- "bracketed"
        for (j in seq_len(3)) {
            midpoint <- (lower + upper) / 2
            fit <- estimate_grid(midpoint, "bisection")
            if (fit$includes_zero) upper <- midpoint else lower <- midpoint
            ci <- rbind(ci, fit)
            save_intervals(ci)
        }
    }
}
first_inclusion_consistent <- all(diff(as.integer(ci$includes_zero[order(ci$Mbar)])) >= 0)
if (!first_inclusion_consistent) status <- "first_grid_crossing_nonmonotone"
write.csv(data.frame(
    outcome = outcome, status = status, last_excludes_zero = lower, first_includes_zero = upper,
    inclusion_monotone_on_evaluated_grid = first_inclusion_consistent, n_evaluated = nrow(ci)
), state_path, row.names = FALSE)
write.csv(data.frame(
    outcome = outcome, started_utc = format(started, tz = "UTC", usetz = TRUE),
    elapsed_seconds = as.numeric(difftime(Sys.time(), started, units = "secs")),
    R = R.version.string, HonestDiD = as.character(packageVersion("HonestDiD")),
    osqp = as.character(packageVersion("osqp")), input_md5 = unname(tools::md5sum(input_path)),
    seed = seed, grid_points = grid_points, l_vec = paste(target_weights, collapse = " "),
    smallest_covariance_eigenvalue = smallest_eigenvalue
), meta_path, row.names = FALSE)
writeLines(capture.output(sessionInfo()), file.path(output, "sessionInfo.txt"))
