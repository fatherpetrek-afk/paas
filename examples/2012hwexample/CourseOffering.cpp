#include "CourseOffering.h"

// Implement the required functions here
CourseOffering::CourseOffering(Course *course, Semester semester, int year){
    this->course = course;
    this->semester = semester;
    this->year = year;

    for (int i=0; i<NUM_POSSIBLE_GRADES; i++) {
        this->gradeLengths[i] = 0;
    }
    for (int i=0; i<NUM_POSSIBLE_GRADES; i++) {
        this->studentGrades[i] = nullptr;
    }
};

CourseOffering::~CourseOffering() {
    for (int i=0; i<NUM_POSSIBLE_GRADES; i++) {
        delete[] this->studentGrades[i];
    }
}

CourseOffering& CourseOffering::assignGrade(int studentId, const Grades& grade) {
    for (int s=0; s<NUM_POSSIBLE_GRADES; s++) {
        for (int r=0; r<gradeLengths[s]; r++) {
            if (studentGrades[s][r] == studentId) {
                if (gradeLengths[s] == 1) {
                    delete[] studentGrades[s];
                    gradeLengths[s] = 0;
                    studentGrades[s] = nullptr;
                    break;
                }
                else {
                    int a=0;
                    int b=0;
                    
                    int *new_old_grade = new int [gradeLengths[s]-1];
                    while (a<gradeLengths[s]&& studentGrades[s][a] < studentId) {
                        new_old_grade[b] = studentGrades[s][a];
                        a++;
                        b++;
                    }
                    a++;
                    while (a<gradeLengths[s]) {
                        new_old_grade[b]=studentGrades[s][a];
                        a++;
                        b++;
                    }           
                    
                    gradeLengths[s]--;
                    delete[] studentGrades[s];
                    studentGrades[s] = new_old_grade;
                    break;
                }
                
            }
        }
    }   
            int * new_this_grade = new int[gradeLengths[grade]+1];
            if (gradeLengths[grade] == 0) {
                studentGrades[grade] = new_this_grade;

                studentGrades[grade][0] = studentId;
                gradeLengths[grade]++;
                return *this;
            }
            else {
                int p=0;
                int q=0;
                while (p < gradeLengths[grade]  && studentGrades[grade][p] < studentId) p++;
                while (q<p) {
                    new_this_grade[q] = studentGrades[grade][q];
                    q++;
                }
                new_this_grade[p] = studentId;
                q=p+1;
                while (q<gradeLengths[grade]+1) {
                    new_this_grade[q] = studentGrades[grade][q-1];
                    q++;
                }
                delete []studentGrades[grade];
                studentGrades[grade] = new_this_grade;
                gradeLengths[grade]++;
                return *this;
            }
            

    return *(this);
};

double CourseOffering::getGrade(int studentId) const {
    for (int i=0; i<NUM_POSSIBLE_GRADES; i++) {
        for (int j=0; j<gradeLengths[i]; j++) {
            if (studentGrades[i][j] == studentId) {
                Grades grade = static_cast<Grades>(i);
                return gradeToOrdinal(grade);
            }
        }
    }
    return 0;
};

int CourseOffering::compareTo(const CourseOffering &other) const {
    int same_course = this->course->compareTo(*other.course);
    if (same_course != 0) return same_course;

    else {
       int same_year = this->year - other.year;
       if (same_year != 0) return same_year;
       
       else {
            int weight[] ={3,0,1,2};

            int same_sem =weight[this->semester] - weight[other.semester];
            return same_sem;
       }
    }

    return 0;
};

bool CourseOffering::sameCourse(const CourseOffering &other) const {
    return (this->course == other.course);
};

bool CourseOffering::sameSemester(Semester semester, int year) const {
    return (this->year == year && this->semester == semester);
};


// The following functions are implemented for you.
// DO NOT MODIFY THE LINES BELOW.
void CourseOffering::printInfo() const {
    cout << "(" << semesterToString(semester) << " " << year << ") ";
    course->printInfo();
}

void CourseOffering::printOffering() const {
    cout << "Offering of " << semesterToString(semester) << " " << year << "\n";
    for (int i = 0; i < NUM_POSSIBLE_GRADES; i++) {
        if (gradeLengths[i]) {
            cout << "ID(s) of student(s) with " << gradeToString(static_cast<Grades>(i)) << ":\n";
            for (int j = 0; j < gradeLengths[i]; j++) {
                cout << studentGrades[i][j] << (j < gradeLengths[i] - 1 ? ", " : "\n");
            }
        }
    }
}
