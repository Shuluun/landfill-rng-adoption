# Audit open parameter-grid endpoints without changing the sensitivity assumptions.
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 4L)
.libPaths(c(args[[1L]], .libPaths()))
suppressPackageStartupMessages(library(HonestDiD))
stopifnot(as.character(packageVersion("HonestDiD")) == "0.2.8")
input <- read.csv(args[[2L]], stringsAsFactors = FALSE)
original <- read.csv(args[[3L]], stringsAsFactors = FALSE)
output <- args[[4L]]
stopifnot(dir.exists(output), !file.exists(file.path(output, "expanded_grid.csv")))
start <- Sys.time()
data <- input[input$outcome == "concentration_pp", ]
beta <- data[data$kind == "beta", ]$value
sigma <- matrix(data[data$kind == "covariance", ]$value, nrow = 5L, byrow = TRUE)
target <- c(0, .5, .5)
sd_theta <- sqrt(drop(t(target) %*% sigma[3:5, 3:5] %*% target))
stopifnot(length(beta) == 5L, sd_theta > 0, all(original$outcome == "concentration_pp"))

compute <- function(value, factor) {
    bound <- 20 * factor * sd_theta
    grid_points <- 1L + factor * 999L
    messages <- character()
    computed <- withCallingHandlers(
        as.data.frame(createSensitivityResults_relativeMagnitudes(
            betahat = beta, sigma = sigma, numPrePeriods = 2L, numPostPeriods = 3L,
            l_vec = target, method = "C-LF", Mbarvec = value, alpha = .05,
            grid.lb = -bound, grid.ub = bound, gridPoints = grid_points,
            parallel = FALSE, seed = 17261117L
        )),
        warning = function(w) {
            messages <<- c(messages, conditionMessage(w))
            invokeRestart("muffleWarning")
        }
    )
    stopifnot(nrow(computed) == 1L, is.finite(computed$lb), is.finite(computed$ub),
              computed$lb <= computed$ub)
    edge <- computed$lb <= -bound + 1e-9 || computed$ub >= bound - 1e-9
    data.frame(
        Mbar = value, widened_lb = computed$lb, widened_ub = computed$ub,
        widened_includes_zero = computed$lb <= 0 && computed$ub >= 0,
        bound_multiple = 20 * factor, grid_points = grid_points,
        parameter_grid_lower = -bound, parameter_grid_upper = bound,
        parameter_step = 2 * bound / (grid_points - 1L),
        open_endpoint = edge || any(grepl("CI is open", messages, fixed = TRUE)),
        warnings = paste(unique(messages), collapse = " | ")
    )
}

results <- list()
for (i in seq_len(nrow(original))) {
    row <- original[i, ]
    cat("Checking widened concentration grid at Mbar", row$Mbar, "\n")
    flush.console()
    first <- compute(row$Mbar, 2L)
    last <- if (first$open_endpoint) compute(row$Mbar, 4L) else first
    original_includes_zero <- row$lb <= 0 && row$ub >= 0
    results[[i]] <- cbind(
        last, original_lb = row$lb, original_ub = row$ub,
        original_includes_zero = original_includes_zero,
        zero_inclusion_agrees = last$widened_includes_zero == original_includes_zero,
        first_expansion_open = first$open_endpoint, first_expansion_warnings = first$warnings
    )
}
write.csv(do.call(rbind, results), file.path(output, "expanded_grid.csv"), row.names = FALSE)
write.csv(data.frame(
    R = R.version.string, HonestDiD = as.character(packageVersion("HonestDiD")),
    osqp = as.character(packageVersion("osqp")), seed = 17261117L, sd_theta = sd_theta,
    input_md5 = unname(tools::md5sum(args[[2L]])), original_md5 = unname(tools::md5sum(args[[3L]])),
    elapsed_seconds = as.numeric(difftime(Sys.time(), start, units = "secs"))
), file.path(output, "R_CHECK_RECEIPT.csv"), row.names = FALSE)
