##################
## ASSIGNMENT 1 ##
##################
rm(list=ls())

#Importing libraries
library(MASS)  #Loading Functions for linear and nonlinear modeling (e.g., lda() and qda() for discriminant analysis, glm() for generalized linear models).
library(lars)  #LARS, LASSO, Forward stagewise regression

#Loading the housing dataset
my_data <- read.csv("/home/kweku/philemon/data visualisation/ML/housing.csv") 

#read dimension of dataset
dim(my_data)

#read column names
colnames(my_data)

#summary statistics 
summary(my_data)

#read dataset
head(my_data)

#view dataset
#View(my_data)


#check null values
is.na(my_data)
# sum(is.na(my_data))
colSums(is.na(my_data))

#drop rows with missing values
my_cleaned_data <- na.omit(my_data)

head(my_cleaned_data)

summary(my_cleaned_data)

#Check unique values of categorical column
unique(my_cleaned_data$ocean_proximity)

#plot data
plot(my_cleaned_data$housing_median_age , my_cleaned_data$median_house_value)
attach(my_cleaned_data)
plot(housing_median_age , median_house_value)

pairs(
    ~ housing_median_age + total_rooms + total_bedrooms + population + households + median_income + median_house_value,
    data = my_cleaned_data)

plot(my_cleaned_data$housing_median_age , my_cleaned_data$median_income)
attach(my_cleaned_data)
plot(housing_median_age , median_income)

hist(housing_median_age)

boxplot(housing_median_age)
boxplot(my_cleaned_data[,9])


#Fit a simple linear regression model predicting house value using median income. 
#Report the estimated coefficients.


lm.fit=lm(median_house_value~median_income)
lm.fit
summary(lm.fit)
coef(lm.fit)
confint(lm.fit)

plot(median_income,median_house_value)
abline(lm.fit)
abline(lm.fit , lwd = 3, col = "red")


#Fit a multiple regression model using all available predictors. Report the regression summary.
lm.fit=lm(median_house_value~longitude + latitude + housing_median_age + total_rooms + total_bedrooms + population + households + median_income + ocean_proximity)
lm.fit
summary(lm.fit)
round(coef(lm.fit),3)
round(summary(lm.fit)$coefficients,3)
confint(lm.fit)


#Using median income as the sole predictor, fit polynomial regression models of degree 1, 2, 3, and 4.
#polynomial = 1
lm.fit=lm(median_house_value~poly(median_income,1))
lm.fit
summary(lm.fit)
coef(lm.fit)
confint(lm.fit)

#polynomial = 2
lm.fit=lm(median_house_value~poly(median_income,2))
lm.fit
summary(lm.fit)
coef(lm.fit)
confint(lm.fit)

#polynomial = 3
lm.fit=lm(median_house_value~poly(median_income,3))
lm.fit
summary(lm.fit)
coef(lm.fit)
confint(lm.fit)

#polynomial = 4
lm.fit=lm(median_house_value~poly(median_income,4))
lm.fit
summary(lm.fit)
coef(lm.fit)
confint(lm.fit)




# myfn <- function(xx,yy,seed,n){
# 	set.seed(seed)
# 	train=sample(length(yy),length(yy)/2)
# 	out=matrix(,2,4)
# 	
# 	for(j in 1:n){
# 		fit=lm(yy~poly(xx,j),data=my_cleaned_data,subset=train)
# 		out[1,j]=mean(fit$residuals^2)				#training error
# 		out[2,j]=mean((yy-predict(fit,xx))[-train]^2)	#test error
# 	}
# 	
# 	return(out)
# }
# 
# 
# err.1 = myfn(median_income,median_house_value,1,4)
