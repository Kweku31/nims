#include<stdio.h>
#include<math.h>
#define FUNC(x)((x*x*x)-x-1)
int main(){
float c;
int i;
float a=1;
float b=3;
	while(fabs(b-a)>=0.000001){
	if(FUNC(a)==0)
        {
        printf("The root of the function is %f\n",a);
        break;
        }
        else if(FUNC(b)==0) 
        {
        printf("The root of the function is %f\n",b);
        break;
        }
        else if(FUNC(a)*FUNC(b)>0){
        printf("The func(a) and func(b) must have different signs or check your a and b");
        break;
        }
	if(c =(a+b)/2){
	if(FUNC(c)==0)
        {
	printf("The root of the function is %f\n",c);
        break;
        }
	else if (FUNC(a)*FUNC(c)>0){
	a = c;
	}
	else if (FUNC(b)*FUNC(c)>0){
        b = c; 
        }
	}
	}
	printf("The root of the function is %f\n",c);

}
