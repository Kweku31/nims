#!/usr/bin/env Rscript
# Rebuild Figures 4.1--4.5 from an archived experiment or the accompanying extract.
args <- commandArgs(trailingOnly = TRUE)
if (length(args) > 1) stop("Usage: Rscript Codes/generate_figures.R [snapshot_directory]")
script <- sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE))
codes <- dirname(normalizePath(script))
images <- file.path(dirname(codes), "images")
extract <- file.path(codes, "figure_values.csv")
formats <- c(original_source="Source CSV", csv="Rewritten CSV", csv_gzip="CSV + gzip",
             parquet="Parquet", csv_zstd="CSV + Zstd")
model_names <- c(pca="PCA", autoencoder="AE", gzip="gzip", parquet="Parquet", zstd="Zstd")
blue <- "#285878"
orange <- "#C76A28"

if (length(args) == 1) {
  reports <- function(name) read.csv(file.path(args[1], name), stringsAsFactors=FALSE)
  overview <- reports("03_phase_overview.csv")
  evidence <- reports("01_integrated_evidence.csv")
  records <- subset(evidence, dataset=="original" & delivery_scenario=="fresh_data" &
                      network_mode=="ssh" & codec=="native")
  stopifnot(nrow(records)==11, all(records$empirical_ssh_eligible=="True"),
            all(records$remote_sha256_verified=="True"),
            all(records$receiver_recovery_passed=="True"),
            all(records$model_reuse_count_assumed==1))
  label <- unname(model_names[records$method])
  label <- ifelse(is.na(records$k), label, paste(label, records$k))
  stopifnot(!anyNA(label), !anyDuplicated(label))
  row <- function(metric, group, value) data.frame(metric, group, value)
  base_metric <- function(key) {
    r <- subset(overview, phase=="2" & metric==key & mode=="ssh")
    stopifnot(setequal(r$configuration, names(formats)), !anyDuplicated(r$configuration))
    row(key, unname(formats[r$configuration]), r$value)
  }
  retained <- subset(overview, phase=="3" & metric=="predictors_retained")
  reduced <- !is.na(records$k)
  values <- rbind(base_metric("file_bytes"), base_metric("packaging_mean_seconds"),
                  base_metric("transfer_mean_seconds"),
                  row("retained", retained$configuration, retained$value),
                  row("r2", label[reduced], records$R2_retained_variation_observed_STANDARDIZED[reduced]),
                  row("fresh_seconds", label, records$effective_delivery_seconds))
  stopifnot(all(is.finite(values$value)), nrow(values)==41)
  write.csv(values, extract, row.names=FALSE)
} else {
  values <- read.csv(extract, stringsAsFactors=FALSE)
}

series <- function(key) {
  rows <- values[values$metric==key, ]
  setNames(rows$value, rows$group)
}
figure <- function(name, draw, margins=c(3.7,4.4,0.6,0.8)) {
  png(file.path(images,paste0(name,".png")), width=7.4, height=3.65, units="in", res=240)
  on.exit(dev.off())
  par(mar=margins, mgp=c(2.4,0.7,0), las=1, bty="l", family="sans", cex=.98)
  draw()
}
figure("baseline_sizes", function() {
  barplot(series("file_bytes")[formats]/1e6, col=blue, border=NA, ylab="File size (decimal MB)")
})
figure("baseline_times", function() {
  times <- rbind(series("packaging_mean_seconds")[formats], series("transfer_mean_seconds")[formats])
  barplot(times, col=c(blue,orange), border=NA, ylab="Mean time (s)", ylim=c(0,60))
  legend("topright", c("Preparation","SCP copy"), fill=c(blue,orange), bty="n", cex=.88)
})
figure("feature_retention", function() {
  counts <- sort(series("retained"))
  labels <- sub("FS_([0-9]+)_clinical_review","\\1% protected",names(counts))
  labels <- sub("FS_([0-9]+)_missingness","\\1% missingness",labels)
  labels[labels=="FS_00_no_missingness_filter"] <- "No missingness filter"
  barplot(counts, names.arg=labels, horiz=TRUE, col=blue, border=NA,
          xlab="Predictors retained (of 40)", xlim=c(0,41))
  abline(v=40, lty=2, col=blue)
}, c(3.7,9.4,0.6,0.8))
figure("reconstruction_r2", function() {
  k <- c(2,4,8,16)
  scores <- series("r2")
  plot(k, scores[paste("PCA",k)], type="o", pch=16, col=blue, lwd=2,
       ylim=c(0,1), xlab="Latent dimensions", ylab=expression("Observed-value reconstruction "*R^2),
       xaxt="n")
  axis(1, at=k)
  lines(k,scores[paste("AE",k)],type="o",pch=17,lty=2,lwd=2,col=orange)
  legend("topleft",c("PCA","Autoencoder"),col=c(blue,orange),pch=c(16,17),lty=c(1,2),bty="n")
})
figure("fresh_data_times", function() {
  times <- sort(series("fresh_seconds"))
  barplot(times, horiz=TRUE, col=blue, border=NA, xlab="Estimated fresh-data delivery time (s)",
          cex.names=.82, space=.25)
}, c(3.7,5.4,0.6,0.8))
