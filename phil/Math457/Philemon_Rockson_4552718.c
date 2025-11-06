#include<stdio.h>
#include<math.h>

#define FN(x) ((x*x*x)-x-1)
#define DV(x) (3*x*x -1)
int main(){
int v;
printf("Finding the root for x^3 - x -1\n");
printf("Input 1 for Bisection Method\n");
printf("Input 2 for Newton-Raphson Method\n");
printf("Input 3 for Secant Method\n");
printf("Please input your choice :\n");
scanf("%d",&v);

if(v==1){
float a=1;
float b=3;
float c;
        while(fabs(b-a)>=0.000001){
        if(FN(a)==0)
        {
        printf("The root of the function is %f\n",a);
        break;
        }
        else if(FN(b)==0) 
        {
        printf("The root of the function is %f\n",b);
        break;
        }
        else if(FN(a)*FN(b)>0){
        printf("The func(a) and func(b) must have different signs or check your a and b");
        break;
        }
        if(c =(a+b)/2){
        if(FN(c)==0)
        {
        printf("The root of the function is %f\n",c);
        break;
        }
        else if (FN(a)*FN(c)>0){
        a = c;
        }
        else if (FN(b)*FN(c)>0){
        b = c; 
        }
        }
        }
        printf("The root of the function is %f\n",c);
}
if(v==2){
float c;
float p=1;
float q;
        while(fabs(FN(q))>=0.000001){
        q = p - (FN(p)/DV(p));
        p = q;
        if(DV(p) == 0){
        printf("Error!!,Method fails\n");
	break;
        } 
        }
        printf("The root of the function is %f\n",q);
} 
if(v==3){
float a=1;
float b=3;
float u;
        while(fabs(FN(u))>=0.000001){
        u = a -((b-a)/(FN(b)-FN(a)))*FN(a);
        a=b;
        b=u;
	if(FN(b)==FN(a)){
        printf("Error!!,Method fails\n");
        break;
        }
        }
        printf("The root of the function is %f\n",u);


}
 






}

